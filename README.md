# IoT-CondicaoDeEquipamento

# Condição de Equipamento — Monitor de pH com ESP32 + MQTT

## Integrantes

- Gabrieli Eduarda Lembeck
- Heloisa Rebello Cabral
- Julio Bezerra de Mattos Manoel
- Mileine da Silva de Freitas
- Thomas Henry Steinback

## Família temática

**Internet das Coisas (IoT) — Monitoramento de condições de equipamentos.**

## O que o sistema faz

Um ESP32 lê um sensor de pH (PH-4502C), mostra o valor num display OLED e **publica a leitura via Wi-Fi em um tópico MQTT**. Um servidor (FastAPI em Docker) **assina esse tópico**, compara o pH com a faixa normal e **publica um comando MQTT** de volta. O ESP32 **assina o tópico de comando** e só então aciona o atuador.

O firmware **não decide** nada sobre o atuador: sem a rede e o broker MQTT, o atuador não é acionado.

## Arquitetura

```
 Sensor pH ──► ESP32 ──Wi-Fi──► Broker MQTT ──► Servidor (ph-server)
                                 (publish)          │  assina sistema/aquario/ph
                                                    │  compara com a faixa normal
 Atuador ◄── ESP32 ◄──Wi-Fi──── Broker MQTT ◄───────┘  publica sistema/aquario/atuador
 (LED GPIO2)   (subscribe + callback)

 ESP32 ──HTTP POST /api/ph──► Servidor ──► Dashboard web (apenas visualização)
```

## Tópicos MQTT

| Tópico                     | Quem publica | Quem assina | Conteúdo                         |
| -------------------------- | ------------ | ----------- | -------------------------------- |
| `sistema/aquario/ph`      | ESP32        | Servidor    | `{"ph":7.02,"tensao":2.513}`     |
| `sistema/aquario/atuador` | Servidor     | ESP32       | `ON` ou `OFF` (mensagem retida)  |

Broker: `test.mosquitto.org:1883`. Faixa normal: pH 6.5 a 7.5 (configurável no `docker-compose.yml`).

## Hardware

- ESP32 DevKit
- Sensor de pH PH-4502C (saída analógica no GPIO 35)
- Display OLED SSD1306 128x64 (I2C: SDA 21, SCL 22)
- **Atuador:** LED embutido da placa (GPIO 2), sem ligações extras

## Como rodar

**Servidor**

```bash
cd ph-server/ph-server
docker compose up --build
```

Dashboard: `http://<IP-da-máquina>:8000` · Estado do MQTT: `http://<IP-da-máquina>:8000/api/status`

**Firmware**

1. Copie `codigo/secrets.example.h` para `codigo/secrets.h` e preencha Wi-Fi e IP do servidor.
2. Bibliotecas: `PubSubClient`, `Adafruit SSD1306`, `Adafruit GFX`.
3. Grave `codigo/leituraPh.c++` no ESP32 (`codigo/calibracao.c++` serve só para calibrar o sensor).

## Como demonstrar o requisito de IoT

1. Com tudo rodando, coloque o sensor numa solução fora da faixa: o servidor publica `ON` e o LED acende.
2. Pare o servidor (`docker compose stop`): o pH continua sendo lido, mas o atuador **não muda mais de estado**. Isso prova que o comando vem da rede, não do firmware.
3. Opcional: acompanhe os tópicos com `mosquitto_sub -h test.mosquitto.org -t "sistema/aquario/#" -v`.

## Primeiro risco técnico

**Risco:** o broker público pode ficar instável ou indisponível durante a apresentação.

**Mitigação:** os tópicos usam prefixo único e o comando é publicado como mensagem retida. Se necessário, trocar o broker por um Mosquitto local alterando `mqtt_server` no firmware e `MQTT_BROKER` no `docker-compose.yml`.
