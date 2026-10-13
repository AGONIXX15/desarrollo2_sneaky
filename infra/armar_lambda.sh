#!/bin/sh
# Copia core/ y lambda_retry/ a infra/build/lambda para que sam build los empaquete juntos.
set -e
cd "$(dirname "$0")/.."
destino=infra/build/lambda
rm -rf "$destino"
mkdir -p "$destino"
cp -r core lambda_retry "$destino"/
cp lambda_retry/requirements.txt "$destino"/requirements.txt
find "$destino" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "listo en $destino"
