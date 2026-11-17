#!/usr/bin/env bash
# Cria infra/mosquitto/passwd (com hash) para os usuários backend, sonda-01 e ctrl-01, a partir do .env.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${MQTT_BACKEND_PASSWORD:?defina no .env}" "${MQTT_SONDA_PASSWORD:?defina no .env}" "${MQTT_CTRL_PASSWORD:?defina no .env}"
: > infra/mosquitto/passwd
docker run --rm -v "$PWD/infra/mosquitto:/m" \
  -e B="$MQTT_BACKEND_PASSWORD" -e S="$MQTT_SONDA_PASSWORD" -e C="$MQTT_CTRL_PASSWORD" \
  eclipse-mosquitto:2.0.20 sh -c '
    mosquitto_passwd -b /m/passwd backend "$B" &&
    mosquitto_passwd -b /m/passwd sonda-01 "$S" &&
    mosquitto_passwd -b /m/passwd ctrl-01 "$C" &&
    chmod 644 /m/passwd'
echo "Senhas gravadas em infra/mosquitto/passwd (com hash). Reinicie o broker: docker compose restart mosquitto"
