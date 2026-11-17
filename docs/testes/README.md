# Testes de falha (R10) — roteiro e evidências

Para cada cenário, guarde nesta pasta: log do Serial (`.txt`), print do MQTT Explorer e a consulta ao banco.
Nomeie como `cenario1_wifi_serial.txt`, `cenario1_mqtt.png`, `cenario1_banco.txt` etc.

Consultas úteis (no servidor): `docker compose exec postgres psql -U aquario -d aquario`

## 1. Queda do Wi-Fi

1. Com tudo em AUTO, desligue o roteador (ou o hotspot) por 60 s.
2. Esperado:
   - Sonda: OLED continua mostrando pH/temperatura; buzzer continua funcionando se sair da faixa crítica.
   - Controlador: após `rede_timeout_s` (30 s) vai para **SEGURO (causa rede)** — bombas e cooler OFF.
   - Broker publica o Last Will `offline` dos dois; a interface mostra os selos **offline** e, após 2 min, o alerta.
   - Religue: os dois reconectam sozinhos (sem travar o loop); o controlador volta para AUTO após 30 s estável.
3. Banco: `select * from dispositivo_status order by ts desc limit 10;` e `select * from alertas order by criado_em desc limit 5;`

## 2. Broker parado

1. `docker compose stop mosquitto` por 60 s, depois `docker compose start mosquitto`.
2. Esperado: firmware tenta reconectar a cada 5 s sem travar; controlador em SEGURO (rede); backend loga
   "desconectado do broker" e abre o alerta `broker_indisponivel` (> 30 s). Ao voltar, tudo reconecta.

## 3. Sensor desconectado

1. Desconecte o fio amarelo (DQ) do DS18B20 **ou** o Po do PH-4502C.
2. Esperado: telemetria com `"valido": false` (−127 °C ou ADC saturado); Sonda em **FALHA_SENSOR**; Controlador em
   **SEGURO (causa sensor)**; alerta `falha_sensor_*` e `modo_seguro`. Reconectando, a Sonda volta a NORMAL após
   5 leituras válidas, mas o Controlador **só** sai de SEGURO com o comando `modo=AUTO` pela interface.
3. Banco: `select * from medicoes where valido = false order by ts desc limit 5;`

## 4. Comando inválido ou repetido

1. **Repetido:** na tabela "Últimos comandos" da interface, clique em ↻ num comando já confirmado (republica o
   mesmo `commandId`). Esperado: ack `rejeitado` com `E_DUPLICADO`, nada é executado.
2. **Inválido:** no MQTT Explorer (usuário `backend`), publique em `aquario/v1/ctrl-01/cmd`:
   `{"v":1,"commandId":"11111111-1111-4111-8111-111111111111","ts":null,"origem":"usuario","acao":"dosar","params":{"alvo":"bomba_ph_mais","duracao_ms":99999},"expira_em_s":10}`
   Esperado: ack `rejeitado` com `E_PAYLOAD_INVALIDO`. Com `"acao":"voar"` → `E_ACAO_DESCONHECIDA`.
3. **Intertravamento:** coloque em SEGURO e tente dosar → `E_INTERTRAVAMENTO`.
4. Banco: `select fase, resultado, codigo, ts from comando_eventos order by id desc limit 10;`
