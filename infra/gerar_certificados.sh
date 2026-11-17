#!/usr/bin/env bash
# Gera a CA própria e o certificado do broker (R16). Rode uma vez na máquina/VM do Docker.
#   MQTT_PUBLIC_HOST no .env = nome DNS ou IP que os ESP32 usam para chegar ao broker.
# Saída em infra/certs/: ca.crt (vai também para o firmware, em secrets.h), ca.key (NÃO versionar),
# server.crt, server.key.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
HOST="${MQTT_PUBLIC_HOST:-localhost}"
DIR=infra/certs
mkdir -p "$DIR"

if [ ! -f "$DIR/ca.key" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=Aquario Inteligente CA" \
    -keyout "$DIR/ca.key" -out "$DIR/ca.crt"
  echo "CA criada em $DIR/ca.crt (validade 10 anos)"
fi

# SAN: nome usado pelos ESP32 + nome interno do compose + localhost
if [[ "$HOST" =~ ^[0-9.]+$ ]]; then SAN="IP:$HOST"; else SAN="DNS:$HOST"; fi
SAN="$SAN,DNS:mosquitto,DNS:localhost,IP:127.0.0.1"

openssl req -newkey rsa:2048 -nodes -subj "/CN=$HOST" -keyout "$DIR/server.key" -out "$DIR/server.csr"
printf "subjectAltName=%s\nextendedKeyUsage=serverAuth\n" "$SAN" > "$DIR/server.ext"
openssl x509 -req -in "$DIR/server.csr" -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" -CAcreateserial \
  -days 825 -out "$DIR/server.crt" -extfile "$DIR/server.ext"
chmod 644 "$DIR/server.key"   # o mosquitto roda como usuário sem privilégio dentro do container
echo "Certificado do broker para: $SAN"
echo
echo "Copie o conteúdo de $DIR/ca.crt para MQTT_CA_CERT em firmware/sonda/secrets.h e firmware/controlador/secrets.h"
