# Como rodar

## 1. Servidor (máquina Linux com Docker)

Precisa de Docker com Compose v2 e `openssl`. As portas **8883** (MQTT) e **8000** (interface) devem estar liberadas.
A 8000 deve ficar só na rede local, porque a interface não tem login.

Copie o zip para a máquina e descompacte:

```bash
unzip IoT-CondicaoDeEquipamento-N3-sem-login.zip
cd IoT-CondicaoDeEquipamento
```

Crie o arquivo de configuração:

```bash
cp .env.example .env
```

Abra o `.env` e preencha:

| Variável | O que colocar |
|---|---|
| `POSTGRES_PASSWORD` | uma senha qualquer |
| `MQTT_BACKEND_PASSWORD`, `MQTT_SONDA_PASSWORD`, `MQTT_CTRL_PASSWORD` | uma senha para cada um; anote as duas últimas, elas vão para as placas |
| `MQTT_PUBLIC_HOST` | o IP ou nome desta máquina, o mesmo que os ESP32 vão usar para chegar nela |
| `PUBLIC_BASE_URL` | `http://<mesmo IP>:8000` |
| `CALLMEBOT_PHONE`, `CALLMEBOT_APIKEY` | opcional, só se quiser os alertas no WhatsApp |

Gere os certificados e as senhas do broker. Faça isso **antes** de subir o Docker:

```bash
bash infra/gerar_certificados.sh
bash infra/gerar_senhas.sh
```

Suba tudo:

```bash
docker compose up -d --build
```

Confira se está no ar:

```bash
docker compose ps
curl http://localhost:8000/api/saude
```

Os três serviços devem aparecer como `running`, e o `curl` deve trazer `"broker_conectado": true`.

Depois abra `http://<IP da máquina>:8000` no navegador. O painel abre direto.

## 2. Placas ESP32 (no computador com a Arduino IDE 2)

Uma vez só, instale:

- o core **esp32** da Espressif;
- as bibliotecas PubSubClient, ArduinoJson, OneWire, DallasTemperature, Adafruit SSD1306 e Adafruit GFX Library.

Para cada placa (`firmware/sonda` e `firmware/controlador`):

1. Copie o `secrets.example.h` para `secrets.h`, na mesma pasta.
2. No `secrets.h`, preencha:
   - o Wi-Fi;
   - `MQTT_HOST`, igual ao `MQTT_PUBLIC_HOST` do `.env`;
   - a senha MQTT daquela placa (a da sonda ou a do controlador);
   - em `MQTT_CA_CERT`, o conteúdo do arquivo `infra/certs/ca.crt`, que foi gerado no servidor.
3. Abra o `.ino`, escolha a placa **ESP32 Dev Module** e grave pela USB. **Desligue a fonte de 12 V/5 V enquanto grava.**

Em até 1 minuto, os dois dispositivos devem aparecer como online no painel.

### Alternativa: gravar pelo VS Code (PlatformIO)

Cada firmware tem um `platformio.ini` na própria pasta. A Arduino IDE ignora esse arquivo, então os dois jeitos funcionam.

1. Instale o **VS Code** e a extensão **PlatformIO IDE**.
2. Em **File → Open Folder**, abra `firmware/sonda` (ou `firmware/controlador`). Abra a pasta do firmware, não a raiz do repositório.
3. Crie o `secrets.h` nessa pasta, igual ao passo acima.
4. Na barra azul de baixo do VS Code, clique em **✓ Build** para compilar e em **→ Upload** para gravar. O ícone de tomada abre o **Serial Monitor** (115200).

Na primeira vez, o PlatformIO baixa sozinho o core ESP32 3.x (pioarduino, o mesmo que o CI usa) e as bibliotecas. Isso leva alguns minutos e precisa de internet.

Se a porta COM não aparecer no Windows, instale o driver USB da placa (CP210x ou CH340, conforme o chip da sua ESP32).

## 3. Comandos do dia a dia (no servidor)

| Para | Comando |
|---|---|
| Ver os logs | `docker compose logs -f backend` |
| Parar tudo | `docker compose down` |
| Subir de novo | `docker compose up -d` |
| Atualizar depois de mudar o código | `docker compose up -d --build` |

## Se algo não funcionar

**Placas offline:**

- confira se o `MQTT_HOST` do `secrets.h` é o mesmo do `MQTT_PUBLIC_HOST`;
- confira se o `ca.crt` colado na placa é o da geração atual dos certificados;
- confira se a porta 8883 está aberta.

**Mosquitto não sobe:** os scripts do passo 1 não foram rodados antes do `docker compose up`. Para corrigir:

1. rode `docker compose down`;
2. se o Docker criou uma pasta chamada `infra/mosquitto/passwd`, apague essa pasta;
3. rode os dois scripts de novo;
4. suba de novo com `docker compose up -d --build`.

**Página não abre:** veja os logs do backend com `docker compose logs backend`.
