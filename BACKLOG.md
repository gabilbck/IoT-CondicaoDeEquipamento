# Backlog — Condição de Equipamento
 
## Tarefas do projeto (Monitor de pH — ESP32 + MQTT)
 
| ID  | Tarefa                                                               | Status  |
| --- | --------------------------------------------------------------------- | ------- |
| T01 | Criar repositório no GitHub                                          | Feito   |
| T02 | Criar README inicial                                                  | Feito   |
| T03 | Definir o sensor a ser usado (pH, PH-4502C)                          | Feito   |
| T04 | Levantar os componentes disponíveis (ESP32, OLED, PH-4502C)          | Feito   |
| T05 | Montar o sensor de pH no ESP32 (GPIO 35 + divisor resistivo 10k/10k) | Feito   |
| T06 | Testar leitura bruta do sensor (sketch `codigo/calibracao.c++`)      | Feito   |
| T07 | Calibrar o sensor e levantar `PH_SLOPE`/`PH_OFFSET`                  | Feito   |
| T08 | Identificar o modelo do display (OLED SSD1306 128x64)                | Feito   |
| T09 | Conectar o display ao ESP32 (I2C: SDA 21 / SCL 22)                    | Feito   |
| T10 | Exibir tensão, pH e estado do atuador no display                     | Feito   |
| T11 | Implementar leitura filtrada (múltiplas amostras + recorte de outliers) | Feito |
| T12 | Detectar saturação do ADC e registrar aviso no Serial                | Feito   |
| T13 | Conectar o ESP32 ao Wi-Fi                                             | Feito   |
| T14 | Implementar reconexão automática de Wi-Fi após queda                 | Feito   |
| T15 | Mover credenciais do Wi-Fi para `secrets.h` (fora do Git)            | Feito   |
| T16 | Publicar a leitura de pH via MQTT (`sistema/aquario/ph`)             | Feito   |
| T17 | Configurar o broker MQTT com TLS na porta 8883                       | Feito   |
| T18 | Implementar o servidor (FastAPI) e assinar o tópico de pH            | Feito   |
| T19 | Implementar a lógica de comparação do pH com a faixa normal (6.5–7.5) | Feito  |
| T20 | Publicar comando `ON`/`OFF` em `sistema/aquario/atuador` (qos 1, retain) | Feito |
| T21 | Definir o atuador (LED embutido do ESP32, GPIO 2)                    | Feito   |
| T22 | Assinar o tópico de comando no ESP32 e acionar o LED via callback MQTT | Feito |
| T23 | Implementar reconexão automática ao broker MQTT                      | Feito   |
| T24 | Criar endpoint `POST /api/ph` para alimentar o dashboard              | Feito   |
| T25 | Criar dashboard web (`static/index.html`) com atualização automática | Feito   |
| T26 | Criar endpoint `/api/status` com o estado da conexão MQTT            | Feito   |
| T27 | Containerizar o servidor (Docker + `docker-compose.yml`)             | Feito   |
| T28 | Testar leitura com solução dentro da faixa normal (pH neutro)        | Feito   |
| T29 | Testar leitura com solução fora da faixa normal (aciona o atuador)   | Feito   |
| T30 | Testar que o atuador não muda de estado com o servidor parado        | Feito   |
| T31 | Registrar o primeiro risco técnico (instabilidade do broker público) | Feito   |
 
## Pendências / próximos passos
 
| ID  | Tarefa                                                                                   | Status  |
| --- | ------------------------------------------------------------------------------------------ | ------- |
| P01 | Publicar confirmação MQTT de execução do comando de volta ao servidor (tópico dedicado)   | A fazer |
| P02 | Criar testes automatizados (ex.: lógica de decisão do servidor, parser de payload MQTT)   | A fazer |
| P03 | Validar e registrar fisicamente a montagem do circuito (sensor + divisor resistivo)        | A fazer |
| P04 | Avaliar remover os `delay()` pontuais restantes (amostragem, conexão inicial) por temporização não bloqueante completa | A fazer |
 
## Adequação ao critério IoT da N1 (sensor → MQTT → comando → atuador)
 
| ID  | Tarefa                                                          | Status |
| --- | ----------------------------------------------------------------- | ------ |
| T32 | ESP32 publicar leitura de pH em `sistema/aquario/ph`              | Feito  |
| T33 | Servidor assinar `sistema/aquario/ph` (paho-mqtt)                 | Feito  |
| T34 | Servidor comparar pH com a faixa e publicar em `.../atuador`      | Feito  |
| T35 | ESP32 assinar `sistema/aquario/atuador` e acionar LED (GPIO 2)    | Feito  |
| T36 | Mover credenciais do Wi-Fi para `secrets.h` (fora do Git)         | Feito  |
| T37 | Teste: parar servidor e confirmar que o atuador não muda          | Feito  |
 


