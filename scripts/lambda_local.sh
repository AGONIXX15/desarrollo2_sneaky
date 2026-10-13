#!/bin/sh
# Corre la Lambda del ciclo una vez contra el docker compose, con la misma imagen que usa AWS.
# sam local invoke no sirve aquí: solo pasa las variables declaradas en el template
# y DATABASE_URL/AMQP_URL en AWS vienen de SSM.
set -e
cd "$(dirname "$0")/.."
RED=notificaciones_default
PUERTO=${PUERTO_LAMBDA:-9001}

if ! docker network inspect "$RED" >/dev/null 2>&1; then
  echo "No existe la red $RED. Levanta primero el compose: docker compose up -d" >&2
  exit 1
fi

sh infra/armar_lambda.sh >/dev/null
(cd infra && sam build --use-container >/dev/null)

docker rm -f lambda-ciclo >/dev/null 2>&1 || true
trap 'docker stop lambda-ciclo >/dev/null 2>&1 || true' EXIT
docker run -d --rm --name lambda-ciclo --platform linux/amd64 --network "$RED" -p "$PUERTO":8080 \
  -v "$PWD/infra/.aws-sam/build/FuncionCiclo:/var/task:ro" \
  -e DATABASE_URL=postgresql://notif:notif@db:5432/notificaciones \
  -e AMQP_URL=amqp://guest:guest@rabbitmq:5672/ \
  -e MAIL_BACKEND=smtp -e SMTP_HOST=mailpit -e SMTP_PORT=1025 \
  public.ecr.aws/lambda/python:3.12 lambda_retry.handler.handler >/dev/null

url="http://localhost:$PUERTO/2015-03-31/functions/function/invocations"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if respuesta=$(curl -sf -XPOST "$url" -d '{}' 2>/dev/null); then
    break
  fi
  sleep 1
done
echo "$respuesta"

if [ -z "$respuesta" ] || echo "$respuesta" | grep -q errorMessage; then
  echo "La Lambda falló. Logs:" >&2
  docker logs lambda-ciclo 2>&1 | tail -20 >&2
  exit 1
fi
