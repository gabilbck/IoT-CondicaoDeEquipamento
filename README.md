# Aquário Inteligente — pH e temperatura sob controle, de qualquer lugar

Projeto da disciplina de Internet das Coisas (2026/2): **Condição de Equipamento**.

## Integrantes

- Gabrieli Eduarda Lembeck
- Heloisa Rebello Cabral
- Julio Bezerra de Mattos Manoel
- Mileine da Silva de Freitas
- Thomas Henry Steinback

## Problema e usuário

**Usuário:** o aquarista (doméstico ou de loja pequena) que passa o dia fora e mantém peixes ou plantas
sensíveis a variações da água.

**Problema:** pH e temperatura mudam ao longo do dia. Fora da faixa da espécie, isso causa estresse, doença e
morte. A medição manual com kit é feita de vez em quando, e ninguém percebe o problema quando está longe do aquário.

## O que o sistema faz (N3)

- **Mede:** a **Sonda** (`sonda-01`, ESP32) lê pH (PH-4502C) e temperatura (DS18B20) sem bloquear o loop,
  valida as leituras e mostra tudo no OLED. Fora da faixa crítica, toca o buzzer — **com ou sem rede**.
- **Decide e corrige:** o **backend** aplica as regras R8 (média de 5 min do pH → dose pH+/pH−, com intervalo
  mínimo e limite por hora; temperatura com histerese → aquecedor/cooler) e manda comandos ao **Controlador**
  (`ctrl-01`, ESP32), que aciona as bombas, o aquecedor e o cooler com **intertravamento local**, **limite de
  dose por timer** e **estado SEGURO** (máquina de estados BOOT/AUTO/MANUAL/SEGURO).
- **Confirma:** cada comando tem `commandId` e passa por `enviado → recebido → executado → confirmado`
  (ou `rejeitado` / `falhou` / `expirado`), visível na interface.
- **Avisa:** alertas no **WhatsApp** (CallMeBot) para pH/temperatura fora da faixa > 10 min, dispositivo
  offline, falha de sensor, modo SEGURO e broker fora do ar.
- **Mostra:** interface web (sem login), valores atuais, online/offline,
  alertas, comandos, faixas e painel analítico (24 h / 7 dias, média móvel, % fora da faixa, doses/dia, uptime).
- **Roda em containers:** Mosquitto (TLS + senha + ACL) + PostgreSQL + backend FastAPI, com `docker compose up -d`.

Contrato MQTT v1: **[CONTRATOS.md](CONTRATOS.md)** · Proposta completa: [docs/CP12_proposta_upgrade.md](docs/CP12_proposta_upgrade.md)

## Estrutura

```
CONTRATOS.md              contrato MQTT v1 (tópicos, payloads, comandos, erros)
compose.yaml              mosquitto + postgres + backend
.env.example              variáveis (copiar para .env)
infra/
  gerar_certificados.sh   CA própria + certificado do broker
  gerar_senhas.sh         usuários MQTT (backend, sonda-01, ctrl-01)
  mosquitto/              mosquitto.conf e ACL
backend/
  app/                    FastAPI: contrato, ingestão, ciclo de comando, regras, alertas, API, interface
  alembic/                migrações do banco
  tests/                  pytest (contrato, regras, ciclo de comando, alertas, API)
firmware/
  sonda/                  sonda.ino  (+ secrets.example.h)
  controlador/            controlador.ino  (+ secrets.example.h)
docs/
  hardware/mapa_de_pinos.md   pinos e ligações ponto a ponto
  testes/                     roteiro e evidências dos testes de falha (R10)
codigo/, ph-server/       versão da N1 (histórico)
.github/workflows/ci.yml  testes + compilação dos firmwares (R18)
```

## Como rodar

### Pré-requisitos

- Uma máquina Linux (VM na nuvem ou notebook) com **Docker** e **Docker Compose v2**, porta **8883** (MQTT/TLS)
  e **8000** (interface) liberadas.
- **Arduino IDE 2** (ou `arduino-cli`) com o core **esp32** da Espressif e as bibliotecas: PubSubClient,
  ArduinoJson (v7), OneWire, DallasTemperature, Adafruit SSD1306, Adafruit GFX Library.
- `openssl` (para gerar os certificados).

### 1. Servidor (broker + banco + backend)

```bash
git clone https://github.com/gabilbck/IoT-CondicaoDeEquipamento.git
```

```bash
cd IoT-CondicaoDeEquipamento
```

```bash
cp .env.example .env
```

Edite o `.env`: senhas, `MQTT_PUBLIC_HOST` (DNS ou IP pelo qual os ESP32 chegam ao servidor),
`PUBLIC_BASE_URL` e, se quiser WhatsApp, `CALLMEBOT_PHONE` / `CALLMEBOT_APIKEY`
(ative mandando "I allow callmebot to send me messages" para o número da CallMeBot).

```bash
./infra/gerar_certificados.sh
```

```bash
./infra/gerar_senhas.sh
```

```bash
docker compose up -d
```

Abra `http://<servidor>:8000` (não há login). Logs: `docker compose logs -f backend`.

> **Atenção:** sem login, qualquer pessoa que alcance a porta 8000 pode enviar comandos (dosar, OTA) e mudar as
> faixas. Deixe a porta 8000 acessível só na rede local ou atrás de VPN/firewall; só a 8883 precisa ficar pública.

### 2. Firmware

Para cada placa (`firmware/sonda` e `firmware/controlador`):

1. Copie `secrets.example.h` para `secrets.h` na mesma pasta e preencha Wi-Fi, `MQTT_HOST` (igual ao
   `MQTT_PUBLIC_HOST`), senha MQTT do dispositivo e cole o conteúdo de `infra/certs/ca.crt` em `MQTT_CA_CERT`.
2. Abra o `.ino` na Arduino IDE, placa **ESP32 Dev Module**, esquema de partição padrão (tem duas partições de
   app, necessárias para a OTA) e grave pela USB. **Desligue a fonte de 12 V/5 V externa enquanto grava pela USB.**

Ou pela linha de comando:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 --upload -p /dev/ttyUSB0 firmware/sonda
```

Ou pelo **VS Code** com a extensão **PlatformIO**: abra a pasta `firmware/sonda` (ou `firmware/controlador`) como projeto, crie o `secrets.h` como acima e use **Upload** na barra do PlatformIO. Detalhes em [docs/COMO_RODAR.md](docs/COMO_RODAR.md).

### 3. Atualização OTA (R17)

1. Aumente `FW_VERSAO` no `.ino` e gere o binário (Arduino IDE: *Sketch → Exportar binário compilado*).
2. Envie o `.bin` e dispare a OTA:

```bash
curl -F arquivo=@controlador.ino.bin http://<servidor>:8000/api/firmware
```

```bash
curl -X POST -H "Content-Type: application/json" -d '{"device_id":"ctrl-01","arquivo":"<arquivo devolvido acima>","versao":"1.0.1"}' http://<servidor>:8000/api/ota
```

O dispositivo baixa, confere o sha256, reinicia e só aceita a versão nova se conectar ao broker em até 3 min
(senão volta para a anterior). A versão aparece no tópico `estado` e o comando fica **confirmado**.

### 4. Testes

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest
```

O GitHub Actions roda os testes e compila os dois firmwares a cada push e pull request.
Roteiro dos testes de falha com hardware: [docs/testes/README.md](docs/testes/README.md).

## API (resumo)

Nenhuma rota exige login.

| Método | Rota |
|---|---|
| GET | `/api/estado`, `/api/historico`, `/api/analitico`, `/api/alertas`, `/api/comandos`, `/api/config`, `/api/mensagens-invalidas` |
| POST | `/api/comandos`, `/api/comandos/{id}/reenviar`, `/api/firmware`, `/api/ota` |
| PUT | `/api/config` |

Documentação interativa em `http://<servidor>:8000/docs`.

## Licença

MIT — ver [LICENSE](LICENSE).
