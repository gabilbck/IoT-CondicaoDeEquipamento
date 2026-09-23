

Readme · MD
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
 
## Problema e proposta
 
O projeto monitora a condição da água de um sistema (ex.: aquário/reservatório) através da leitura contínua do pH. Em vez de o próprio microcontrolador decidir localmente quando agir, a decisão é tomada por um servidor que recebe a leitura via rede e devolve um comando — cumprindo o requisito da disciplina de que o caminho sensor → atuador passe obrigatoriamente pela rede e pelo broker MQTT.
 
## Como o sistema funciona hoje
 
1. **Leitura do sensor:** o ESP32 lê o sensor de pH PH-4502C no pino `GPIO 35` a cada ~1 segundo. Para reduzir ruído, são coletadas 15 amostras (`analogReadMilliVolts`), elas são ordenadas e a média é calculada apenas com o quartil central (recorte dos 25% mais altos e mais baixos), descartando outliers.
2. **Conversão de tensão:** a tensão lida no pino é multiplicada pelo `FATOR_DIVISOR` (2.0, referente a um divisor resistivo 10k/10k) para reconstituir a tensão real de saída do módulo PH-4502C, já que o ADC do ESP32 satura por volta de 3,1 V. Se a média ficar acima de `MV_SATURADO` (3100 mV), o firmware registra um aviso de saturação no Serial.
3. **Cálculo do pH:** aplica-se a reta de calibração `pH = PH_SLOPE * tensao + PH_OFFSET` (valores atuais: `PH_SLOPE = -5.70`, `PH_OFFSET = 21.34`), obtidos previamente com o sketch auxiliar `codigo/calibracao.c++`.
4. **Publicação via MQTT:** o ESP32 publica `{"ph": <valor>, "tensao": <valor>}` no tópico `sistema/aquario/ph`. Essa é a única via de saída da leitura para fora do dispositivo.
5. **Decisão no servidor:** o servidor (FastAPI, `ph-server/ph-server/app.py`) está assinado no tópico `sistema/aquario/ph`. A cada mensagem recebida, compara o pH com a faixa normal (`PH_MIN`/`PH_MAX`, padrão 6.5–7.5) e só publica um novo comando (`ON`/`OFF`) no tópico `sistema/aquario/atuador` quando o estado muda — a mensagem é publicada com `qos=1` e `retain=True`, para que o ESP32 receba o último comando assim que (re)conectar ao broker.
6. **Execução do comando:** o ESP32 está assinado em `sistema/aquario/atuador`. O callback MQTT (`aoReceberMensagem`) é o **único** trecho do firmware que altera o pino do atuador (`GPIO 2`, LED embutido da placa): ele liga ou desliga o LED conforme o payload recebido (`ON`/`OFF`) e ignora qualquer outra mensagem. Não existe nenhuma comparação de faixa nem decisão local no ESP32 — a leitura sempre sai pela rede e o acionamento sempre entra pela rede.
7. **Exibição local:** o display OLED (SSD1306, I2C `SDA 21` / `SCL 22`) mostra tensão, pH e o estado atual do atuador (rotulado como "Atuador (MQTT)"), atualizado tanto a cada nova leitura quanto a cada novo comando recebido.
8. **Dashboard web:** paralelamente ao MQTT, o ESP32 também envia a leitura por `HTTP POST` para `/api/ph` no servidor (função `enviarLeitura`), apenas para alimentar o histórico e o dashboard (`static/index.html`). Esse envio HTTP é só para exibição — **não** participa da decisão sobre o atuador, que acontece inteiramente via MQTT.
9. **Reconexões automáticas:** o `loop()` do ESP32 verifica o estado do Wi-Fi a cada iteração e reconecta automaticamente se cair; a reconexão ao broker MQTT é tentada a cada 2 segundos (`reconectarMQTT`) sem travar o restante do loop (controle por `millis()`, não por `delay()` bloqueante no laço principal).
### O que NÃO está implementado atualmente
 
- O ESP32 **não publica uma confirmação separada** de volta ao broker informando que o comando foi executado (não há um tópico do tipo `.../confirmacao`). A única confirmação visível hoje é local, no display OLED ("Atuador (MQTT): ON/OFF") e no Serial. O PDF de diretrizes lista "confirmação de estado ou de ação executada" como item avaliado dentro de "Atendimento aos requisitos" — vale a pena decidir, como equipe, se isso deve ser adicionado antes da entrega.
- Não há testes automatizados (unitários ou de integração) no repositório; a evidência de que o sistema foi testado hoje é o procedimento manual descrito em "Como demonstrar o requisito de IoT" abaixo.
- O tratamento de "dado inválido" existe no servidor (o `try/except` em `ao_receber` descarta mensagens MQTT que não sejam um JSON válido com campo `ph`), mas o firmware do ESP32 não valida limites de faixa da leitura antes de publicar (ele só sinaliza saturação do ADC no Serial).
## Arquitetura
 
```
 Sensor pH ──► ESP32 ──Wi-Fi──► Broker MQTT ──► Servidor (ph-server)
                                 (publish,          │  assina sistema/aquario/ph
                                  TLS :8883)         │  compara com a faixa normal
 Atuador ◄── ESP32 ◄──Wi-Fi──── Broker MQTT ◄───────┘  publica sistema/aquario/atuador
 (LED GPIO2)   (subscribe + callback)                    (qos=1, retain)
 
 ESP32 ──HTTP POST /api/ph──► Servidor ──► Dashboard web (apenas visualização)
```
 
O firmware não decide nada sobre o atuador: sem rede e sem o broker MQTT respondendo, o atuador não muda de estado (ver seção de demonstração).
 
## Tópicos MQTT
 
| Tópico                     | Quem publica | Quem assina | Conteúdo                                  |
| --------------------------- | ------------- | ------------ | ------------------------------------------ |
| `sistema/aquario/ph`       | ESP32         | Servidor     | `{"ph":7.02,"tensao":2.513}`               |
| `sistema/aquario/atuador`  | Servidor      | ESP32        | `ON` ou `OFF` (qos 1, mensagem retida)     |
 
- **Broker:** `test.mosquitto.org`, porta **8883** (MQTT sobre TLS — a porta 1883 sem TLS costuma ser bloqueada em redes de faculdade/empresa). Tanto o firmware (`espClient.setInsecure()`) quanto o servidor (`tls_set(cert_reqs=ssl.CERT_NONE)`) usam TLS sem validar o certificado, por ser um broker público de teste.
- **Faixa normal considerada:** pH 6.5 a 7.5, configurável via variáveis de ambiente `PH_MIN`/`PH_MAX` no `docker-compose.yml`.
- **Prefixo dos tópicos:** `sistema/aquario/...`, escolhido para reduzir a chance de colisão com outras equipes usando o mesmo broker público.
## Hardware
 
- ESP32 DevKit
- Sensor de pH PH-4502C (saída analógica no `GPIO 35`, com divisor resistivo 10k/10k na entrada)
- Display OLED SSD1306 128x64 (I2C: `SDA 21`, `SCL 22`, endereço `0x3C`)
- **Atuador:** LED embutido da placa (`GPIO 2`), sem ligações extras — acionado exclusivamente pelo comando MQTT recebido do servidor
## Estrutura do repositório
 
```
codigo/
  leituraPh.c++          # Firmware principal (sensor + OLED + Wi-Fi + MQTT)
  calibracao.c++          # Sketch auxiliar só para calibrar o sensor (lê ADC/mV cru)
  secrets.example.h       # Modelo de credenciais (copiar para secrets.h)
  secrets.h                # Credenciais reais — fora do controle de versão (.gitignore)
ph-server/ph-server/
  app.py                   # Servidor FastAPI: assina/publica MQTT, expõe API e dashboard
  docker-compose.yml       # Configuração do container (variáveis MQTT, faixa de pH etc.)
  Dockerfile
  requirements.txt         # fastapi, uvicorn, pydantic, paho-mqtt
  static/index.html        # Dashboard web (consulta a API a cada 3s)
BACKLOG.md                 # Backlog de tarefas da equipe
LICENSE                    # MIT
```
 
## Como rodar
 
**Servidor**
 
```bash
cd ph-server/ph-server
docker compose up --build
```
 
- Dashboard: `http://<IP-da-máquina>:8000`
- Estado do MQTT: `http://<IP-da-máquina>:8000/api/status`
- Última leitura: `http://<IP-da-máquina>:8000/api/ph/latest`
- Histórico (até 50 leituras em memória): `http://<IP-da-máquina>:8000/api/ph/historico`
**Firmware**
 
1. Copie `codigo/secrets.example.h` para `codigo/secrets.h` e preencha o SSID/senha do Wi-Fi (rede 2,4 GHz — o ESP32 não conecta em 5 GHz) e o IP do servidor (`SERVIDOR_URL`).
2. Instale as bibliotecas: `PubSubClient`, `Adafruit SSD1306`, `Adafruit GFX`.
3. Grave `codigo/leituraPh.c++` no ESP32. O arquivo `codigo/calibracao.c++` **não** faz parte do funcionamento normal do sistema — ele serve apenas para levantar os valores de `PH_SLOPE`/`PH_OFFSET` antes de gravar o firmware principal.
## Como demonstrar o requisito de IoT (sensor → rede → decisão → rede → atuador)
 
1. Com tudo rodando, coloque o sensor numa solução fora da faixa normal (pH < 6.5 ou > 7.5): o servidor publica `ON` em `sistema/aquario/atuador` e o LED do ESP32 acende.
2. Pare o servidor (`docker compose stop`): o ESP32 continua lendo e publicando o pH normalmente, mas **o atuador não muda mais de estado**, porque nenhum comando novo chega pelo tópico. Isso evidencia que o acionamento depende da rede e do servidor, e não de uma decisão local no firmware.
3. Opcional — acompanhar os tópicos diretamente no broker: `mosquitto_sub -h test.mosquitto.org -p 8883 --capath /etc/ssl/certs -t "sistema/aquario/#" -v`.
## Aderência aos critérios de avaliação da N1 (conforme PDF de diretrizes da defesa)
 
O PDF "Diretrizes para Defesa do Projeto — N1" define que o **Projeto técnico (P, 30% da N1)** é avaliado de forma assíncrona sobre o repositório entregue, com um **crivo eliminatório** antes de qualquer nota e, em seguida, os critérios de "Atendimento aos requisitos" (20%), "Funcionamento e integração" (25%), "Arquitetura e qualidade técnica" (20%), "Tratamento de falhas" (15%), "Testes" (10%) e "Repositório e documentação" (10%). Abaixo, o mapeamento de cada ponto do PDF para o que está implementado neste projeto.
 
### Crivo eliminatório
 
| Exigência do crivo | Situação neste projeto |
| --- | --- |
| Sensoriamento real | Atendido — sensor de pH PH-4502C, leitura analógica real no `GPIO 35` |
| Processamento no ESP32 | Atendido — filtragem, conversão de tensão e cálculo do pH feitos no firmware |
| Leitura saindo por rede | Atendido — publicação em `sistema/aquario/ph` via MQTT |
| Decisão via MQTT (não ligação direta sensor-atuador) | Atendido — a decisão ON/OFF é calculada no servidor a partir da leitura recebida por MQTT; o ESP32 não compara faixa localmente |
| Comando remoto | Atendido — comando chega ao ESP32 pelo tópico `sistema/aquario/atuador` |
| Confirmação de ação | Parcial — há confirmação **local** (OLED e Serial); não há publicação MQTT de confirmação de volta ao servidor (ver "O que NÃO está implementado atualmente") |
| Telemetria contínua | Atendido — publicação a cada ciclo de leitura (~1s) enquanto o Wi-Fi/MQTT estiverem conectados |
 
### Atendimento aos requisitos (20%)
 
| Item verificado no PDF | Situação neste projeto |
| --- | --- |
| ESP32 presente | Sim |
| Pelo menos um sensor real | Sim — PH-4502C |
| Pelo menos um atuador, alerta ou saída física real | Sim — LED embutido (GPIO 2) |
| Circuito funcional | Depende da montagem física (divisor resistivo + sensor); o firmware está preparado para o circuito descrito no README |
| Leitura real do sensor, com validação básica do dado | Sim — média filtrada por quartil central e checagem de saturação do ADC |
| Firmware minimamente organizado (não monolítico com `delay()`) | Parcial — o laço principal usa `millis()` para leitura e reconexão sem bloquear o recebimento de comandos MQTT; ainda existem `delay()` pontuais em rotinas específicas (amostragem do sensor, conexão inicial de Wi-Fi, mensagens no OLED), que não travam o sistema como um todo |
| Logs no monitor serial | Sim — leitura, saturação do ADC, conexão Wi-Fi/MQTT e comandos recebidos são todos logados |
| Conexão Wi-Fi, com reconexão automática após queda | Sim — verificada e refeita a cada iteração do `loop()` |
| Publicação de telemetria via MQTT | Sim — tópico `sistema/aquario/ph` |
| Tópico de comando, recebido e executado pelo dispositivo | Sim — tópico `sistema/aquario/atuador`, tratado em `aoReceberMensagem` |
| Confirmação de estado ou de ação executada | Parcial — apenas local (OLED/Serial), sem publicação MQTT de volta |
 
### Funcionamento e integração (25%)
 
O sistema roda de ponta a ponta com os componentes reais descritos acima (sensor → ESP32 → MQTT → servidor → MQTT → atuador), incluindo o caminho de exibição em tempo real no dashboard web. O passo a passo de demonstração ao vivo está na seção "Como demonstrar o requisito de IoT".
 
### Arquitetura e qualidade técnica (20%)
 
- Firmware dividido em funções com responsabilidade única (`conectarWiFi`, `lerTensaoFiltrada`, `publicarMQTT`, `enviarLeitura`, `mostrarNoOLED`, `aoReceberMensagem`, `reconectarMQTT`).
- Separação clara de tópicos MQTT por finalidade (`.../ph` para telemetria, `.../atuador` para comando), com prefixo dedicado à equipe.
- Decisões documentadas em comentários no próprio código (ex.: por que a porta MQTT é 8883 e não 1883, por que existe o divisor resistivo, por que o HTTP POST não participa da decisão do atuador).
- Credenciais isoladas em `secrets.h`, fora do controle de versão.
### Tratamento de falhas (15%)
 
- Reconexão automática de Wi-Fi (`conectarWiFi` chamada sempre que `WiFi.status() != WL_CONNECTED`).
- Reconexão automática ao broker MQTT a cada 2 segundos, sem bloquear o restante do `loop()` (`reconectarMQTT`).
- Servidor descarta mensagens MQTT malformadas ou sem o campo `ph` (`try/except` em `ao_receber`), registrando o erro no log.
- Comando publicado com `retain=True`, garantindo que o ESP32 receba o último estado do atuador mesmo após reconectar.
- O ESP32 ignora qualquer payload no tópico de comando que não seja exatamente `ON` ou `OFF`.
### Testes (10%)
 
A evidência atual de teste é o roteiro manual descrito em "Como demonstrar o requisito de IoT": leitura fora da faixa aciona o atuador, e parar o servidor comprova que o acionamento depende da rede/MQTT (o LED não muda mais de estado). Não há testes automatizados no repositório até o momento — isso é apontado em "O que NÃO está implementado atualmente".
 
### Repositório e documentação (10%)
 
Este README traz integrantes, família temática, descrição do problema, arquitetura, tópicos MQTT, hardware, estrutura de pastas e instruções de execução (servidor e firmware). O `BACKLOG.md` documenta o andamento das tarefas da equipe, incluindo uma seção específica dedicada ao critério sensor → MQTT → comando → atuador exigido pela disciplina.
 
## Primeiro risco técnico
 
**Risco:** o broker público (`test.mosquitto.org`) pode ficar instável ou indisponível durante a apresentação.
 
**Mitigação:** os tópicos usam prefixo único (`sistema/aquario/...`) e o comando é publicado como mensagem retida (`retain=True`). Se necessário, o broker pode ser trocado por um Mosquitto local alterando `mqtt_server`/`mqtt_port` no firmware (`codigo/leituraPh.c++`) e `MQTT_BROKER`/`MQTT_PORT` no `docker-compose.yml`.
 
## Licença
 
Distribuído sob licença MIT — ver arquivo `LICENSE`.