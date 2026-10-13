# Servicio de notificaciones

Microservicio de Desarrollo II (Univalle). Los otros equipos (hoy Inventario y Fabricación) nos llaman con `POST /notificaciones`. Guardamos la notificación, la publicamos en una cola para que el worker la entregue por webhook al equipo destino, y mandamos correo a los destinatarios suscritos. Cada 5 minutos una Lambda en AWS reintenta lo que haya quedado pendiente.

Python 3.12, FastAPI, SQLAlchemy 2, Postgres (Neon), RabbitMQ (CloudAMQP), Brevo para correos, Render para la API y AWS Lambda + EventBridge para los reintentos. Las razones de cada decisión están en `docs/DECISIONES.md` y el diagrama en `docs/arquitectura.puml`.

## Qué corre dónde

| Dónde | Qué |
|---|---|
| Render | La API y, en el mismo proceso, el worker que consume la cola y hace los webhooks |
| Neon | Postgres |
| CloudAMQP | Exchange `notificaciones` y una cola `notif.<equipo>` por equipo destino |
| Brevo | Envío de correos |
| AWS | EventBridge cada 5 min → Lambda que corre el ciclo de reintentos. Los secretos están en SSM, los fallos van a una cola SQS y una alarma avisa por correo |

En local todo eso se reemplaza con docker compose: Postgres, RabbitMQ y Mailpit (atrapa los correos en vez de Brevo).

## Herramientas

Para trabajar en local:

| Herramienta | Para qué | Versión probada |
|---|---|---|
| git | clonar el repo | cualquiera |
| Docker + Docker Compose v2 | levantar Postgres, RabbitMQ, Mailpit y la API | Docker 29, Compose 5 |
| uv | instala Python 3.12 y las dependencias | 0.13 |
| PostgreSQL (binarios del servidor) | los tests levantan un Postgres temporal con `pg_ctl` | 16 o más |
| curl | probar los endpoints | cualquiera |

Solo para la Lambda y el despliegue en AWS:

| Herramienta | Para qué |
|---|---|
| AWS SAM CLI | construir y desplegar la Lambda (`sam build`, `sam deploy`) |
| AWS CLI v2 | credenciales (`aws configure`) y cargar los parámetros en SSM |

Cuentas para producción (todas tienen plan gratis): Neon, CloudAMQP, Brevo, Render y AWS.

### Instalación

Arch:

    sudo pacman -S git docker docker-compose postgresql aws-cli-v2
    sudo systemctl enable --now docker
    sudo usermod -aG docker $USER      # cerrar sesión y volver a entrar
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env        # o abrir otra terminal
    uv tool install aws-sam-cli

Ubuntu / Debian:

    sudo apt install git curl postgresql
    sudo systemctl disable --now postgresql   # solo queremos los binarios, el Postgres de verdad va en docker
    # Docker: seguir https://docs.docker.com/engine/install/ubuntu/ (trae el plugin de compose)
    sudo usermod -aG docker $USER      # cerrar sesión y volver a entrar
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env
    uv tool install aws-sam-cli
    # AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

`apt` instala la versión de Postgres de la distro (14 en Ubuntu 22.04, 16 en 24.04). Cualquiera de esas sirve para los tests. `pg_ctl` no queda en el PATH, así que antes de correr los tests:

    ls /usr/lib/postgresql                            # ver qué versión quedó
    export PG_CTL=/usr/lib/postgresql/16/bin/pg_ctl   # con ese número

macOS:

    brew install git postgresql@16 awscli uv
    uv tool install aws-sam-cli
    export PG_CTL=$(brew --prefix postgresql@16)/bin/pg_ctl   # postgresql@16 no se enlaza al PATH
    # Docker Desktop: https://www.docker.com/products/docker-desktop/

En Mac con Apple Silicon la Lambda se construye y corre emulando x86_64 (así está en el template), funciona pero es más lenta.

En Windows usar WSL2 con Ubuntu y seguir los pasos de Ubuntu. Docker Desktop se integra con WSL.

Para revisar que todo quedó:

    docker compose version && uv --version && "${PG_CTL:-pg_ctl}" --version && sam --version && aws --version

## Correr en local

    git clone https://github.com/AGONIXX15/desarrollo2_sneaky.git
    cd desarrollo2_sneaky
    docker compose up -d --build

La primera vez tarda un par de minutos descargando imágenes. El contenedor de la API corre las migraciones al arrancar, y la migración inicial crea los equipos `inventario`, `fabricacion` y `notificaciones` con sus 4 tipos de notificación.

| URL | Qué es |
|---|---|
| http://localhost:8000/docs | Swagger de la API |
| http://localhost:8000/health | health check |
| http://localhost:15672 | panel de RabbitMQ (guest / guest) |
| http://localhost:8025 | Mailpit, ahí llegan los correos |

Crear las API keys (cada equipo puede tener máximo 2 activas; la key se muestra una sola vez y en la BD solo queda el hash):

    docker compose exec api python scripts/crear_api_key.py inventario
    docker compose exec api python scripts/crear_api_key.py fabricacion
    docker compose exec api python scripts/crear_api_key.py notificaciones

Guardar las keys que imprime en variables, porque los ejemplos de abajo las usan:

    export INV=<key de inventario>
    export FAB=<key de fabricacion>
    export NOTIF=<key de notificaciones>

Para ver los logs: `docker compose logs -f api`. Para apagar todo: `docker compose down` (con `-v` también se borra la BD).

Si tenías el stack levantado desde una versión anterior del repo (cuando el compose no tenía `name:`), bajarlo primero con `docker compose -p <nombre de la carpeta> down`, porque si no chocan los puertos.

### API fuera de docker

Útil para trabajar con `--reload`. Se dejan en compose solo los servicios:

    docker compose up -d db rabbitmq mailpit
    cp .env.example .env
    uv sync
    uv run alembic upgrade head
    uv run python scripts/crear_api_key.py inventario
    uv run uvicorn app.main:app --reload

## Probar el flujo

Con la key de inventario en `$INV`:

    # suscribir un destinatario a un tipo
    curl -X POST localhost:8000/notificaciones/destinatarios -H "X-API-Key: $INV" \
      -H "Content-Type: application/json" \
      -d '{"nombre":"Bodega","email":"bodega@example.com","tipos":["STOCK_BAJO_INSUMO"]}'

    # registrar una notificación
    curl -X POST localhost:8000/notificaciones -H "X-API-Key: $INV" \
      -H "Content-Type: application/json" \
      -d '{"tipo":"STOCK_BAJO_INSUMO","productoId":7,"nombre":"Harina","stockActual":2,"stockMinimo":10}'

    # ver cómo va
    curl localhost:8000/notificaciones/estado/<id> -H "X-API-Key: $INV"

Responde 201 con el id. En el estado debe aparecer `publicada` y el correo debe verse en Mailpit. Si se repite el mismo evento mientras la alerta sigue activa responde 200 con `duplicada: true` y el mismo id. Para cerrar la alerta se manda el mismo body con `"evento": "REPUESTO"`.

Los campos que pide cada tipo están en `migrations/versions/0001_inicial.py` (JSON Schema). Un body que no cumpla el schema responde 422.

## Probar los reintentos

1. `docker compose stop rabbitmq mailpit`
2. Registrar una notificación como arriba. Responde 201, pero el estado queda `pendiente_publicacion` y el correo con `intentos: 1`.
3. `docker compose start rabbitmq mailpit`
4. El ciclo ignora lo creado hace menos de 1 minuto y los correos esperan 5 minutos para reintentar. Para no esperar se pueden correr las fechas hacia atrás:

        docker compose exec db psql -U notif -d notificaciones -c "
          UPDATE notificaciones SET creada_at = creada_at - interval '10 minutes';
          UPDATE envios_correo SET proximo_intento_at = now() - interval '1 minute' WHERE enviado_at IS NULL;"

5. Correr el ciclo, de cualquiera de estas dos formas:
   - Desde la API, con la key de notificaciones: `curl -X POST localhost:8000/notificaciones/ciclo -H "X-API-Key: $NOTIF"`
   - Con la Lambda real: `sh scripts/lambda_local.sh`. Construye el paquete con SAM y lo corre una vez en la imagen oficial de Lambda (`public.ecr.aws/lambda/python:3.12`) conectada a la red del compose. Usa el puerto 9001, se cambia con `PUERTO_LAMBDA=9100 sh scripts/lambda_local.sh`. Si la Lambda falla, muestra los logs y sale con error.
6. La respuesta es un resumen (`publicadas: 1, correos_enviados: 1, ...`). El estado pasa a `publicada` y el correo llega a Mailpit.

`sam local invoke` no sirve para esta prueba, porque solo pasa las variables declaradas en el template y en AWS `DATABASE_URL` y `AMQP_URL` vienen de SSM. Por eso existe `lambda_local.sh`.

## Tests

    uv sync
    uv run pytest
    uv run ruff check .

Levantan un Postgres temporal con `pg_ctl`, aplican las migraciones y usan fakes para la cola y el correo, así que no necesitan Docker. Si `pg_ctl` no está en el PATH, exportar `PG_CTL` con la ruta.

## Desplegar

### 1. Servicios externos

- **Neon**: crear el proyecto y copiar la connection string con pooler (el host lleva `-pooler`). Tiene que terminar en `?sslmode=require`. Si las migraciones dan problemas con el pooler, correrlas una vez desde local con la URL directa (sin `-pooler`): `DATABASE_URL='<url directa>' uv run alembic upgrade head`.
- **CloudAMQP**: crear una instancia Little Lemur y copiar la URL AMQPS.
- **Brevo**: crear una API key (SMTP & API → API Keys) y verificar el remitente que va en `MAIL_FROM`.

### 2. Render

1. New → Blueprint, y escoger este repo. Render lee `render.yaml` y crea el web service con el `Dockerfile`.
2. Llenar las variables `DATABASE_URL`, `AMQP_URL`, `BREVO_API_KEY` y `MAIL_FROM`.
3. Al arrancar corre las migraciones solo. Revisar `https://<servicio>.onrender.com/health`.
4. Crear las API keys desde local apuntando a Neon:

        DATABASE_URL='<url de neon>' uv run python scripts/crear_api_key.py inventario

En el plan gratis Render duerme el servicio después de 15 minutos sin tráfico. La Lambda le hace un GET a `/health` en cada corrida para mantenerlo despierto, porque el worker de webhooks vive en ese proceso.

### 3. AWS

    aws configure    # access key de un usuario IAM con permisos de CloudFormation, Lambda, SSM, SQS, SNS, CloudWatch e IAM

Cargar los parámetros en SSM. Tienen que existir los cuatro, porque si falta uno la Lambda falla de entrada en vez de correr a medias:

    aws ssm put-parameter --type SecureString --name /notificaciones/DATABASE_URL --value '<url de neon>'
    aws ssm put-parameter --type SecureString --name /notificaciones/AMQP_URL --value '<url amqps de cloudamqp>'
    aws ssm put-parameter --type SecureString --name /notificaciones/BREVO_API_KEY --value '<key de brevo>'
    aws ssm put-parameter --type SecureString --name /notificaciones/RENDER_HEALTH_URL --value 'https://<servicio>.onrender.com/health'

Construir y desplegar:

    sh infra/armar_lambda.sh
    cd infra
    sam build --use-container
    sam deploy --guided

`armar_lambda.sh` copia `core/` y `lambda_retry/` a `infra/build/lambda` para que la Lambda use el mismo código que la API. `--use-container` compila las dependencias en la misma imagen de Lambda, así da igual el sistema operativo de cada uno.

En `sam deploy --guided` pide `AlertaEmail` (el correo que recibe la alarma cuando falla el ciclo) y `MailFrom`. Lo demás puede quedar por defecto. Guardar la configuración en `samconfig.toml` para que los siguientes despliegues sean solo `sam deploy`. AWS manda un correo para confirmar la suscripción a la alarma y hay que aceptarlo.

Para ver que está corriendo:

    sam logs -n FuncionCiclo --stack-name <stack> --tail

Cada 5 minutos aparece el resumen del ciclo.

## Variables de entorno

| Variable | Por defecto | Qué es |
|---|---|---|
| `DATABASE_URL` | Postgres del compose | URL de Postgres |
| `AMQP_URL` | RabbitMQ del compose | URL de RabbitMQ / CloudAMQP |
| `AMQP_EXCHANGE` | `notificaciones` | exchange donde se publica |
| `MAIL_BACKEND` | `smtp` | `smtp` (Mailpit) o `brevo` |
| `MAIL_FROM`, `MAIL_FROM_NAME` | | remitente de los correos |
| `BREVO_API_KEY` | | solo con `MAIL_BACKEND=brevo` |
| `SMTP_HOST`, `SMTP_PORT` | `localhost`, `1025` | solo con `smtp` |
| `WORKER_ENABLED` | `true` | levanta el consumidor de la cola dentro de la API |
| `RENDER_HEALTH_URL` | | la Lambda le hace GET al terminar |

La Lambda no recibe los secretos directamente. Recibe el nombre del parámetro (`DATABASE_URL_PARAM`, etc.) y lo lee de SSM al arrancar.

## Webhooks

Cada equipo registra su URL con `PUT /notificaciones/callbacks`, y la respuesta trae el secreto para verificar la firma. La URL tiene que ser `https` en el puerto 443 o 8443 y no puede apuntar a una IP privada. Se vuelve a validar antes de cada envío.

Cada POST trae `X-Notification-Id`, `X-Timestamp` y `X-Signature`. La firma es el HMAC-SHA256 en hex de `timestamp + "." + body`:

    import hmac, hashlib
    esperado = hmac.new(secreto.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    hmac.compare_digest(esperado, firma_recibida)

Conviene rechazar si el timestamp tiene más de unos minutos de antigüedad. El body se firma tal cual llega (bytes crudos), no el JSON ya parseado.

## Estructura

    app/            API (routers, auth por API key, worker de webhooks)
    core/           lógica sin FastAPI: modelos, registro, alertas, ciclo, publisher, mailer, webhooks
    lambda_retry/   handler de la Lambda
    infra/          template SAM y armar_lambda.sh
    migrations/     alembic, con seed de equipos y tipos
    scripts/        crear_api_key.py, lambda_local.sh
    tests/
    docs/           decisiones y diagrama
