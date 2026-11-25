#!/usr/bin/env bash
# Cria infra/mosquitto/passwd (com hash) para os usuários backend, sonda-01 e ctrl-01, a partir do .env.
set -euo pipefail
# Git Bash (Windows): não converter caminhos dos argumentos do docker
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
# caminho da pasta no formato que o Docker Desktop entende (C:/... no Git Bash; normal no Linux)
RAIZ="$(pwd -W 2>/dev/null || pwd)"
set -a; . ./.env; set +a
: "${MQTT_BACKEND_PASSWORD:?defina no .env}" "${MQTT_SONDA_PASSWORD:?defina no .env}" "${MQTT_CTRL_PASSWORD:?defina no .env}"
: > infra/mosquitto/passwd
docker run --rm -v "$RAIZ/infra/mosquitto:/m" \
  -e B="$MQTT_BACKEND_PASSWORD" -e S="$MQTT_SONDA_PASSWORD" -e C="$MQTT_CTRL_PASSWORD" \
  eclipse-mosquitto:2.0.20 sh -c '
    mosquitto_passwd -b /m/passwd backend "$B" &&
    mosquitto_passwd -b /m/passwd sonda-01 "$S" &&
    mosquitto_passwd -b /m/passwd ctrl-01 "$C" &&
    chmod 644 /m/passwd'
echo "Senhas gravadas em infra/mosquitto/passwd (com hash). Reinicie o broker: docker compose restart mosquitto"
