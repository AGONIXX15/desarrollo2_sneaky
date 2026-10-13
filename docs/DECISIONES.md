# Decisiones

## EventBridge y Lambda para los reintentos

Contexto: los reintentos necesitan algo que corra cada pocos minutos aunque la API esté dormida (Render free se duerme).

Decisión: una Lambda disparada por EventBridge cada 5 minutos que llama a `ejecutar_ciclo`. De paso hace un GET al `/health` de Render para mantenerlo despierto.

Descartamos el cron de GitHub Actions: el mínimo real es cada 5 minutos con retrasos grandes, se puede desactivar solo si el repo no tiene actividad y no tiene alarmas ni DLQ.

El ciclo tiene un tiempo límite: la Lambda le pasa `limite_segundos` (lo que queda de ejecución menos 40 s de margen) y deja de tomar filas cuando se acaba. Toma de a una fila con `SKIP LOCKED` y hace commit por fila, así no sostiene locks mientras espera a un webhook o a Brevo, y lo que ya se hizo queda guardado aunque se corte. El lote es de 20 por paso y el timeout de la Lambda es de 300 s. Si falla, no se reintenta solo (`MaximumRetryAttempts: 0`): el siguiente ciclo ya lo cubre. La alarma de Errors avisa por SNS al correo del parámetro `AlertaEmail`.

Consecuencias: hay que empaquetar `core/` junto con la Lambda (`infra/armar_lambda.sh`) y los secretos se leen de SSM en runtime. SAM no deja resolver SecureString dentro de `Environment`, así que la Lambda recibe el nombre del parámetro y lo lee con boto3 al arrancar. Si el ciclo revienta, la excepción sube, cae a la DLQ y salta la alarma de Errors.

## CloudAMQP y SQS como plan B

Contexto: necesitamos una cola entre el registro y la entrega del webhook.

Decisión: CloudAMQP, plan gratis Little Lemur, que alcanza para el volumen del proyecto. Exchange direct `notificaciones`, routing key igual al nombre del equipo destino, cola `notif.<equipo>`.

Descartamos usar SQS desde el inicio porque RabbitMQ también corre en local con docker-compose y es lo que vimos en clase.

Consecuencias: el código solo conoce el protocolo `Publisher`. Si CloudAMQP deja de servir, se escribe un `SqsPublisher` y un consumidor equivalente sin tocar el registro ni el ciclo.

## Neon como base de datos

Decisión: Postgres en Neon.

Descartamos Supabase (pausa el proyecto si no hay actividad), Postgres de Render (el plan gratis expira a los 30 días) y RDS (necesita VPC y la Lambda tendría que entrar a ella).

Consecuencias: Neon trae pooler, por eso la Lambda usa `NullPool`. Además tiene branching, que sirve para probar migraciones.

## Qué corre dónde

- Render: la API y el worker de webhooks en el mismo proceso. El worker es una tarea asyncio que arranca en el lifespan (se apaga con `WORKER_ENABLED=false`). Los background workers de Render no son gratis.
- Neon: la base de datos.
- CloudAMQP: la cola.
- Brevo: correos.
- AWS: EventBridge, Lambda, SQS (solo DLQ), CloudWatch y SSM.

## Campos por canal en vez de máquina de estados

Decisión: la notificación no tiene columna `estado`. Cada canal lleva sus fechas y contadores: `publicada_at` e `intentos_publicacion`, `entregada_at` e `intentos_entrega`, y en `envios_correo` `enviado_at` e `intentos`. Se considera fallido lo que llegó a 3 intentos con la fecha en NULL.

El filtro `estado` del listado se calcula a partir de eso: `pendiente_publicacion`, `publicada`, `entregada`, `entrega_fallida`. Agregamos `publicacion_fallida` para el caso de 3 fallos publicando, porque si no se vería como pendiente para siempre.

Descartamos una máquina de estados porque los tres canales avanzan por separado: un correo puede fallar mientras el webhook sale bien, y una sola columna no lo representa.

## Catálogo multi-equipo

Decisión: equipos, tipos, destinos, JSON Schema y TTL viven en la BD (`equipos`, `tipos_notificacion`). Solo el seed de la migración menciona inventario y fabricación. Para sumar un equipo se insertan filas, no se cambia código.

El emisor del tipo es el único que puede registrarlo, incluyendo al admin: el admin solo consulta y dispara el ciclo.

## Webhooks con HMAC y entrega al menos una vez

Decisión: cada equipo registra una URL https con `PUT /notificaciones/callbacks` y recibe un secreto (una sola vez). Cada POST lleva `X-Notification-Id` y `X-Signature`, que es el HMAC-SHA256 en hex del body. El secreto se guarda en claro porque hace falta para firmar.

La URL se rechaza si no es https o si el host resuelve a una IP privada, loopback o link-local.

Cada POST lleva además `X-Timestamp` (segundos epoch) y la firma se calcula sobre `"<timestamp>.<body>"`. Así el receptor puede rechazar mensajes con más de unos minutos de antigüedad y un POST capturado no sirve para repetirlo después. Para verificar: `hmac_sha256(secreto, timestamp + "." + body_crudo)` en hex, comparado con `X-Signature` en tiempo constante.

La URL del callback se vuelve a validar (resolución y chequeo de IP) justo antes de cada POST, no solo al registrarla, por si el DNS pasa a apuntar a una IP interna. Solo se aceptan los puertos 443 y 8443. Si la validación falla cuenta como un intento de entrega fallido.

Al publicar se programa `proximo_intento_entrega_at` a 5 minutos. Si el worker pierde el mensaje antes de intentar el webhook, el ciclo lo toma pasado ese plazo. Si el worker entrega antes, no pasa nada.

Consecuencias: el mensaje de la cola siempre se confirma (ack) y el reintento lo hace el ciclo, hasta 3 intentos. Puede llegar duplicada, así que el equipo destino debe usar `X-Notification-Id` para ignorar repetidas. Si un equipo no tiene callback no es error, consulta por GET.

## Alertas anti-duplicados

Contexto: inventario puede detectar el mismo stock bajo cada minuto.

Decisión: tabla `alertas` con índice único parcial `(tipo, clave) WHERE cerrada_at IS NULL`. El campo que hace de clave se define en el tipo (`campo_clave`). Si no hay campo se usa una clave fija. Si llega un evento con alerta activa se responde 200 con la notificación existente. Una alerta vencida se cierra antes de insertar. El evento `REPUESTO` o `RESUELTA` cierra la alerta sin crear notificación.

Consecuencias: si dos peticiones llegan a la vez, la segunda choca con el índice, se deshace su savepoint y responde 200 con la primera.

## FOR UPDATE SKIP LOCKED en vez del 409

Decisión: cada paso del ciclo selecciona hasta 100 filas con `FOR UPDATE SKIP LOCKED`. Si la API (`POST /notificaciones/ciclo`) y la Lambda corren a la vez, cada una toma filas distintas.

Descartamos devolver 409 cuando ya hay un ciclo corriendo, porque obligaba a llevar un candado aparte.

## Probar el re-send

1. `docker compose up -d`
2. `docker compose stop rabbitmq`
3. Hacer un POST /notificaciones. Responde 201, pero en `GET /notificaciones/estado/{id}` queda `pendiente_publicacion` y `intentos_publicacion = 1`.
4. `docker compose start rabbitmq`
5. `POST /notificaciones/ciclo` con la key de notificaciones (o invocar `lambda_retry.handler.handler` con `DATABASE_URL` apuntando a la BD del compose).
6. El estado pasa a `publicada` y el worker hace el webhook si hay callback.

Para los correos es igual con Mailpit apagado. El reintento solo ocurre cuando pasan los 5 minutos de `proximo_intento_at`.

## Migraciones al arrancar el contenedor

El `Dockerfile` corre `alembic upgrade head` antes de levantar uvicorn. Funciona porque hay una sola instancia de la API. Si algún día hay varias, las migraciones tendrían que ir en un paso aparte del despliegue. El contenedor corre con un usuario sin privilegios y la imagen de uv está fijada a la versión que usamos en local.

## Carrera entre la API y el ciclo

El ciclo ignora las notificaciones creadas hace menos de un minuto para no pisar la tarea de fondo que acaba de crearlas. La tarea de fondo toma la fila con `SKIP LOCKED` y revisa `publicada_at` antes de publicar.

## Ajustes para alinear con el backlog v3

- Los destinatarios se actualizan con `PATCH` (nombre, tipos o activo, también para dar de baja y reactivar), ya no con `PUT` y `DELETE`. Registrar un correo que ya está activo en el mismo equipo responde 409 con el id existente. El listado se pagina (`pagina`, `tamano`, `totalPaginas`, `total`) y filtra por `activo`.
- El callback tiene `activo` (migración `0003`). Un callback desactivado se trata igual que uno sin registrar: el worker no entrega, el ciclo lo ignora y las notificaciones quedan consultables por GET.
- El secreto del callback ya no cambia en cada `PUT`: solo al crearlo o con `regenerarSecreto`.
- El admin puede marcar notificaciones como leídas.
- El `mensaje` de una notificación se calcula con `core/mensajes.py` y no se guarda. Se devuelve en las consultas y en el cuerpo del webhook.
- Los esquemas de cada tipo tienen límites de longitud y rango (migración `0003`). Para cambiar un límite basta otra migración que actualice la fila de `tipos_notificacion`.
- Los listados de notificaciones también devuelven `totalPaginas`.
