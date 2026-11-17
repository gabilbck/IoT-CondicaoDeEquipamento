#pragma once
// Copie para "secrets.h" (mesma pasta) e preencha. secrets.h está no .gitignore e NÃO vai para o GitHub.

// A ESP32 só conecta em redes 2,4 GHz.
#define WIFI_SSID   "NOME_DA_REDE"
#define WIFI_SENHA  "SENHA_DA_REDE"

// Broker próprio (compose.yaml). MQTT_HOST deve ser o MESMO nome/IP usado em MQTT_PUBLIC_HOST no .env.
#define MQTT_HOST    "aquario.exemplo.com"
#define MQTT_PORT    8883
#define MQTT_USUARIO "ctrl-01"           // = deviceId
#define MQTT_SENHA   "troque-ctrl"       // = MQTT_CTRL_PASSWORD do .env

// Conteúdo de infra/certs/ca.crt (gerado por ./infra/gerar_certificados.sh). Usado no MQTT e na OTA https.
static const char MQTT_CA_CERT[] = R"PEM(
-----BEGIN CERTIFICATE-----
COLE AQUI O CONTEÚDO DE infra/certs/ca.crt
-----END CERTIFICATE-----
)PEM";
