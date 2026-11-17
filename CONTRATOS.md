# CONTRATOS.md — Contrato MQTT v1 (congelado em 27/10/2026)

Contrato entre os dispositivos (`sonda-01`, `ctrl-01`) e o backend do **Aquário Inteligente**.
Mudança incompatível só como **v2** (`aquario/v2/...`). Campos novos **e opcionais** podem entrar na v1:
quem recebe ignora campos que não conhece.

Fonte da verdade no código:

| Lado | Arquivo |
|---|---|
| Backend (validação Pydantic) | `backend/app/contrato.py` |
| Firmware da Sonda | `firmware/sonda/sonda.ino` |
| Firmware do Controlador | `firmware/controlador/controlador.ino` |
| Testes do contrato | `backend/tests/test_contrato.py` |

---

## 1. Convenções

- **Codificação:** JSON UTF-8, um objeto por mensagem. Tamanho máximo: 1024 bytes.
- **Campos obrigatórios em todo payload publicado por dispositivo:** `v` (sempre `1`), `deviceId`, `ts`.
- **`ts`:** ISO 8601 em UTC com `Z` (`2026-11-10T21:30:05Z`). Se o dispositivo ainda não sincronizou a hora
  pelo NTP, envia `"ts": null` e `"ts_sync": false`; o backend usa então a hora de chegada.
- **Unidades explícitas:** toda grandeza física vem com `unidade` (`pH`, `°C`) ou com o sufixo no nome
  (`duracao_ms`, `duracao_s`, `rssi_dbm`, `uptime_s`).
- **`deviceId`:** `sonda-01` ou `ctrl-01`. É também o usuário MQTT do dispositivo.
- **`commandId`:** UUID v4 gerado pelo backend. Cada `commandId` é executado **no máximo uma vez**.

## 2. Árvore de tópicos

```
aquario/v1/
├── sonda-01/
│   ├── telemetria   sonda  → backend, ctrl-01     QoS 0  retain não   a cada 2 s
│   ├── estado       sonda  → backend              QoS 1  retain sim   ao mudar + a cada 60 s
│   ├── cmd          backend → sonda               QoS 1  retain não   sob demanda
│   ├── ack          sonda  → backend              QoS 1  retain não   2 por comando
│   └── status       sonda / broker (LWT) → todos  QoS 1  retain sim   ao conectar / ao cair
└── ctrl-01/
    ├── estado       ctrl   → backend              QoS 1  retain sim   ao mudar + a cada 60 s
    ├── cmd          backend → ctrl                QoS 1  retain não   sob demanda
    ├── ack          ctrl   → backend              QoS 1  retain não   2 por comando
    └── status       ctrl / broker (LWT) → todos   QoS 1  retain sim   ao conectar / ao cair
```

### Justificativa de QoS e retain

| Tópico | Por quê |
|---|---|
| `telemetria` QoS 0, sem retain | Chega a cada 2 s; perder uma leitura não muda nada e a próxima corrige. Retain mostraria um valor velho como atual. |
| `estado` QoS 1, retain | É o "retrato" do dispositivo. Retido para que backend e interface saibam o estado logo ao (re)conectar. |
| `cmd` QoS 1, **sem retain** | Comando precisa chegar, mas **nunca** pode ser reexecutado ao reconectar (o retain da N1 fazia isso). Comando perdido vira `expirado` no backend. |
| `ack` QoS 1, sem retain | Precisa chegar para fechar o ciclo; não faz sentido reter. |
| `status` QoS 1, retain + Last Will | Online/offline sempre disponível; o broker publica `offline` sozinho quando o dispositivo cai. |

> **Limitação conhecida (firmware):** a biblioteca `PubSubClient` só **publica** em QoS 0 (assina em QoS 1).
> As publicações dos dispositivos em `estado` e `ack` saem em QoS 0 no nível do protocolo. Compensação:
> `estado` é retido e republicado a cada 60 s; um `ack` perdido faz o comando expirar no backend, que mostra
> isso na interface. O Last Will (`status`) é publicado pelo broker com QoS 1.

## 3. ACL (Mosquitto)

| Usuário | Pode publicar | Pode assinar |
|---|---|---|
| `backend` | `aquario/v1/+/cmd` | `aquario/v1/#` |
| `sonda-01` | `aquario/v1/sonda-01/{telemetria,estado,ack,status}` | `aquario/v1/sonda-01/cmd` |
| `ctrl-01` | `aquario/v1/ctrl-01/{estado,ack,status}` | `aquario/v1/ctrl-01/cmd`, `aquario/v1/sonda-01/telemetria`, `aquario/v1/sonda-01/status` |

Só o backend publica em `.../cmd`. Arquivo: `infra/mosquitto/acl`.

## 4. Payloads

### 4.1 `aquario/v1/sonda-01/telemetria`

```json
{
  "v": 1, "deviceId": "sonda-01", "ts": "2026-11-10T21:30:05Z", "ts_sync": true, "seq": 1532,
  "leituras": [
    { "grandeza": "ph", "valor": 7.12, "unidade": "pH", "valido": true, "tensao_v": 2.531 },
    { "grandeza": "temperatura", "valor": 25.4, "unidade": "°C", "valido": true }
  ],
  "estado_local": "NORMAL"
}
```

| Campo | Tipo | Regra |
|---|---|---|
| `seq` | inteiro ≥ 0 | Contador crescente desde o boot (detecta perda). |
| `leituras[].grandeza` | `ph` \| `temperatura` | |
| `leituras[].valor` | número ou `null` | `null` quando não há leitura. |
| `leituras[].unidade` | `pH` \| `°C` | Deve casar com a grandeza. |
| `leituras[].valido` | booleano | `false` se: pH fora de 0–14 ou ADC saturado; temperatura −127 °C (desconectado) ou fora de 0–45 °C. |
| `leituras[].tensao_v` | número (opcional) | Tensão no Po do PH-4502C, para recalibração. |
| `estado_local` | `NORMAL` \| `ALERTA_LOCAL` \| `FALHA_SENSOR` | Estado da regra local da Sonda. |

### 4.2 `aquario/v1/sonda-01/estado` (retido)

```json
{
  "v": 1, "deviceId": "sonda-01", "ts": "2026-11-10T21:30:00Z", "ts_sync": true,
  "estado_local": "NORMAL", "silenciado_s": 0,
  "ultimo_command_id": null, "fw": "1.0.0", "config_versao": 2, "rssi_dbm": -58, "uptime_s": 3600,
  "config": { "ph_crit_min": 6.0, "ph_crit_max": 8.0, "temp_crit_min": 22.0, "temp_crit_max": 30.0,
              "ph_slope": -5.70, "ph_offset": 21.34, "intervalo_ph_ms": 2000, "intervalo_temp_ms": 5000 }
}
```

### 4.3 `aquario/v1/ctrl-01/estado` (retido)

```json
{
  "v": 1, "deviceId": "ctrl-01", "ts": "2026-11-10T21:30:07Z", "ts_sync": true,
  "modo": "AUTO", "causa_seguro": null,
  "atuadores": { "bomba_ph_mais": "OFF", "bomba_ph_menos": "OFF", "aquecedor": "OFF", "cooler": "OFF" },
  "nivel": "OK", "ultimo_command_id": "6f1c2a7e-4b1d-4a8f-9a63-0c2f5d9e8b11",
  "fw": "1.0.0", "config_versao": 3, "rssi_dbm": -61, "uptime_s": 86400,
  "config": { "dose_max_ms": 5000, "manual_timeout_s": 600, "telemetria_timeout_s": 30, "rede_timeout_s": 30 }
}
```

| Campo | Valores |
|---|---|
| `modo` | `BOOT` \| `AUTO` \| `MANUAL` \| `SEGURO` |
| `causa_seguro` | `null` \| `rede` \| `sensor` \| `comando` \| `config` |
| `atuadores.*` | `ON` \| `OFF`. `aquecedor: ON` = **liberado** para o termostato próprio; `OFF` = bloqueado pelo relé. |
| `nivel` | `OK` \| `BAIXO` (boia aberta ou fio rompido) |

### 4.4 `aquario/v1/<deviceId>/status` (retido, Last Will)

```json
{ "v": 1, "deviceId": "ctrl-01", "status": "online", "ts": "2026-11-10T21:30:07Z", "ts_sync": true, "fw": "1.0.0" }
```

Last Will (publicado pelo broker): `{"v":1,"deviceId":"ctrl-01","status":"offline","ts":null,"ts_sync":false}`.

### 4.5 `aquario/v1/<deviceId>/cmd` (backend → dispositivo)

```json
{ "v": 1, "commandId": "6f1c2a7e-4b1d-4a8f-9a63-0c2f5d9e8b11", "ts": "2026-11-10T21:30:06Z",
  "origem": "regra:ph_baixo", "acao": "dosar", "params": { "alvo": "bomba_ph_mais", "duracao_ms": 1000 },
  "expira_em_s": 10 }
```

| Campo | Regra |
|---|---|
| `origem` | `usuario` \| `regra:<nome>` \| `sistema` |
| `expira_em_s` | 1–600. Se o dispositivo tem hora (`ts_sync`) e `ts + expira_em_s` já passou → `E_EXPIRADO`. |

### 4.6 `aquario/v1/<deviceId>/ack` (dispositivo → backend)

```json
{ "v": 1, "deviceId": "ctrl-01", "ts": "2026-11-10T21:30:06Z", "commandId": "6f1c2a7e-4b1d-4a8f-9a63-0c2f5d9e8b11",
  "fase": "recebido", "resultado": "ok", "codigo": null, "detalhe": null }
```

| Campo | Valores |
|---|---|
| `fase` | `recebido` \| `executado` |
| `resultado` | `ok` \| `rejeitado` \| `falha` |
| `codigo` | `null` ou um código do catálogo de erros |
| `commandId` | `null` só quando o payload do comando era ilegível (`E_PAYLOAD_INVALIDO`). |

## 5. Catálogo de comandos

| `acao` | Dispositivo | `params` e faixas | Aceito nos modos (ctrl) |
|---|---|---|---|
| `dosar` | ctrl-01 | `alvo`: `bomba_ph_mais` \| `bomba_ph_menos`; `duracao_ms`: 100–5000 (e ≤ `dose_max_ms`) | AUTO, MANUAL (só `usuario`) |
| `aquecedor` | ctrl-01 | `estado`: `ON` \| `OFF` | AUTO, MANUAL (só `usuario`) |
| `cooler` | ctrl-01 | `estado`: `ON` \| `OFF` | AUTO, MANUAL (só `usuario`) |
| `modo` | ctrl-01 | `modo`: `AUTO` \| `MANUAL` \| `SEGURO` | todos (menos BOOT) |
| `silenciar` | sonda-01 | `duracao_s`: 60–3600 | — |
| `config` | ambos | chaves da seção 6 (uma ou mais) | todos |
| `ota` | ambos | `url` (http/https), `versao` (texto), `sha256` (64 hex) | todos |

## 6. Chaves de configuração (`acao: "config"`)

Gravadas na NVS do dispositivo; cada `config` aceito incrementa `config_versao`.

| Dispositivo | Chave | Faixa | Padrão |
|---|---|---|---|
| sonda-01 | `ph_crit_min` / `ph_crit_max` | 0–14 (min < max) | 6.0 / 8.0 |
| sonda-01 | `temp_crit_min` / `temp_crit_max` | 0–45 (min < max) | 22.0 / 30.0 |
| sonda-01 | `ph_slope` | −20 a 20 | −5.70 |
| sonda-01 | `ph_offset` | −50 a 50 | 21.34 |
| sonda-01 | `intervalo_ph_ms` | 1000–60000 | 2000 |
| sonda-01 | `intervalo_temp_ms` | 2000–60000 | 5000 |
| ctrl-01 | `dose_max_ms` | 100–5000 | 5000 |
| ctrl-01 | `manual_timeout_s` | 60–3600 | 600 |
| ctrl-01 | `telemetria_timeout_s` | 10–300 | 30 |
| ctrl-01 | `rede_timeout_s` | 10–300 | 30 |

As faixas **das regras do backend** (`ph_min`, `ph_max`, `temp_min`, `temp_max`, intervalo entre doses etc.)
não vão para o dispositivo: ficam na tabela `configuracoes` e são editadas pela interface (`PUT /api/config`).

## 7. Confirmação em duas fases e ciclo do comando (R7)

```
enviado ──ack recebido/ok──► recebido ──ack executado/ok──► executado ──estado bate──► confirmado
   │                            │                              │
   │                            └─ack executado/falha──► falhou │
   ├──ack recebido/rejeitado──► rejeitado (com código)          │
   └──sem conclusão em expira_em_s──────────────────────────────┴──► expirado
```

- **confirmado:** o `estado` publicado pelo dispositivo traz `ultimo_command_id` igual ao comando **e** o
  atuador/modo bate com o pedido (para `dosar`, a bomba já voltou a `OFF`).
- Um `ack` de um comando já em estado final é registrado em `comando_eventos`, mas não muda o estado.

## 8. Catálogo de erros

| Código | Quando |
|---|---|
| `E_PAYLOAD_INVALIDO` | JSON ilegível, campo obrigatório ausente, tipo errado ou parâmetro fora da faixa. |
| `E_VERSAO` | `v` diferente de 1. |
| `E_ACAO_DESCONHECIDA` | `acao` fora do catálogo ou não suportada por aquele dispositivo. |
| `E_DUPLICADO` | `commandId` já visto (os últimos 16 são guardados em RAM). |
| `E_INTERTRAVAMENTO` | Modo não permite (BOOT, SEGURO, MANUAL com origem `regra:*`) ou intertravamento: outra bomba ligada, aquecedor com cooler ligado ou nível baixo, saída de SEGURO com sensor inválido. |
| `E_EXPIRADO` | `ts + expira_em_s` já passou quando o comando chegou. |
| `E_FALHA_EXECUCAO` | Aceito, mas não concluído (dose interrompida por SEGURO, OTA com download ou sha256 errado). |
