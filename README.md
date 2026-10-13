# Servicio de notificaciones

Microservicio de Desarrollo II (Univalle). Los otros equipos (hoy Inventario y Fabricación) nos llaman con `POST /notificaciones`. Guardamos la notificación, la publicamos en una cola para que el worker la entregue por webhook al equipo destino, y mandamos correo a los destinatarios suscritos.

Python 3.12, FastAPI, SQLAlchemy 2, Postgres, RabbitMQ (CloudAMQP en producción), Brevo para correos.

## Arrancar en local

Con Docker:

    docker compose up -d --build
    docker compose exec api python scripts/crear_api_key.py inventario

La API queda en http://localhost:8000/docs, RabbitMQ en http://localhost:15672 (guest/guest) y Mailpit en http://localhost:8025. El contenedor corre las migraciones al arrancar.

Sin Docker de la API (solo db, rabbit y mailpit en compose):

    cp .env.example .env
    uv sync
    uv run alembic upgrade head
    uv run python scripts/crear_api_key.py notificaciones
    uv run uvicorn app.main:app --reload

Cada equipo puede tener máximo 2 keys activas. La key se muestra una sola vez, en la BD solo queda el hash.

## Probar

    curl -X POST localhost:8000/notificaciones -H "X-API-Key: <key inventario>" \
      -H "Content-Type: application/json" \
      -d '{"tipo":"STOCK_BAJO_INSUMO","productoId":7,"nombre":"Harina","stockActual":2,"stockMinimo":10}'

Si se repite el mismo evento mientras la alerta sigue activa responde 200 con el mismo id. Para cerrar la alerta se manda el mismo body con `"evento": "REPUESTO"`.

## Tests

    uv run pytest

Levantan un Postgres temporal con `pg_ctl` (hace falta tenerlo en `/usr/bin`), aplican las migraciones y usan fakes para la cola y el correo. No necesitan Docker.

## Reintentos

`core/ciclo.py` tiene `ejecutar_ciclo`, que republica lo pendiente, reenvía correos fallidos, reintenta webhooks y cierra alertas vencidas. Lo llama la Lambda cada 5 minutos y también `POST /notificaciones/ciclo` con la key de notificaciones. Para probar el re-send ver `docs/DECISIONES.md`.

## Verificar la firma del webhook

Cada POST trae `X-Notification-Id`, `X-Timestamp` y `X-Signature`. La firma es el HMAC-SHA256 en hex de `timestamp + "." + body` con el secreto que devolvió `PUT /notificaciones/callbacks`:

    import hmac, hashlib
    esperado = hmac.new(secreto.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    hmac.compare_digest(esperado, firma_recibida)

Conviene rechazar si el timestamp tiene más de unos minutos de antigüedad. El body se firma tal cual llega (bytes crudos), no el JSON ya parseado.

## Estructura

    app/            API (routers, auth por API key, worker de webhooks)
    core/           lógica sin FastAPI: modelos, registro, alertas, ciclo, publisher, mailer, webhooks
    lambda_retry/   handler de la Lambda
    infra/          template SAM
    migrations/     alembic, con seed de equipos y tipos
    scripts/        crear_api_key.py
    tests/
