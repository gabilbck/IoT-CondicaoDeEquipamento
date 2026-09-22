#pragma once
// Copie este arquivo para "secrets.h" (na mesma pasta) e preencha.
// "secrets.h" está no .gitignore e NÃO deve ir para o GitHub.

// A ESP32 só conecta em redes 2.4GHz (não funciona em 5GHz).
#define WIFI_SSID   "NOME_DA_REDE"
#define WIFI_SENHA  "SENHA_DA_REDE"

// IP da máquina rodando o Docker do ph-server
#define SERVIDOR_URL "http://192.168.0.10:8000/api/ph"
