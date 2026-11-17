/*
 * Aquário Inteligente — firmware do CONTROLADOR (ctrl-01)
 * Bombas peristálticas pH+ (GPIO25) / pH− (GPIO26) via MOSFET IRLZ44N,
 * relé do aquecedor (GPIO32, contato NC) e do cooler (GPIO33, contato NO) — módulo ativo em LOW,
 * boia de nível (GPIO34, fecha = nível OK → LOW).
 *
 * Máquina de estados BOOT → AUTO ⇄ MANUAL, qualquer um → SEGURO (CONTRATOS.md e CP12 §5.3).
 * Intertravamentos locais (valem com ou sem rede):
 *   - nunca pH+ e pH− juntos; dose limitada por timer de hardware (esp_timer) a dose_max_ms (≤ 5 s),
 *     mesmo que a rede caia no meio da dose;
 *   - nunca aquecedor e cooler juntos (ligar o cooler bloqueia o aquecedor antes);
 *   - aquecedor bloqueado com nível baixo (boia aberta ou fio rompido).
 * Estado seguro: bombas e cooler desligados, aquecedor no próprio termostato (relé desenergizado),
 * exceto com nível baixo.
 *
 * Bibliotecas: PubSubClient, ArduinoJson (v7).
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Update.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <time.h>
#include "esp_timer.h"
#include "esp_ota_ops.h"
#include "mbedtls/sha256.h"

#include "secrets.h"

#define FW_VERSAO "1.0.0"   // aumente antes de exportar um binário para OTA
#define DEVICE_ID "ctrl-01"
#define SONDA_ID  "sonda-01"

// ===== Pinos (docs/hardware/mapa_de_pinos.md) =====
#define PIN_BOMBA_MAIS   25  // gate do IRLZ44N (R 220 Ω, pull-down 10 kΩ) — HIGH = bomba ligada
#define PIN_BOMBA_MENOS  26
#define PIN_RELE_AQUEC   32  // IN1 do módulo (ativo em LOW). LOW = relé energizado = NC aberto = aquecedor BLOQUEADO
#define PIN_RELE_COOLER  33  // IN2 do módulo (ativo em LOW). LOW = relé energizado = NO fechado = cooler LIGADO
#define PIN_BOIA         34  // só entrada, pull-up externo 10 kΩ. LOW = boia fechada = nível OK

#define DOSE_LIMITE_MS 5000

// ===== Configuração (NVS) =====
struct Config {
  uint32_t dose_max_ms = 5000;
  uint32_t manual_timeout_s = 600;
  uint32_t telemetria_timeout_s = 30;
  uint32_t rede_timeout_s = 30;
  uint32_t versao = 0;
} cfg;
Preferences prefs;
bool configValida = true;

// ===== Estados =====
enum Modo { BOOT, AUTO, MANUAL, SEGURO };
Modo modo = BOOT;
String causaSeguro = "";
const char* nomeModo(Modo m) { return m == BOOT ? "BOOT" : m == AUTO ? "AUTO" : m == MANUAL ? "MANUAL" : "SEGURO"; }

// estado lógico dos atuadores (aquecedor ON = liberado para o termostato)
bool bombaMais = false, bombaMenos = false, aquecedor = true, cooler = false;
bool nivelOk = true;

// dose em andamento
esp_timer_handle_t timerDose;
volatile bool doseTerminou = false;
String doseCmdId = "";

// ===== Rede =====
WiFiClientSecure net;
PubSubClient mqtt(net);
char tEstado[48], tCmd[48], tAck[48], tStatus[48], tTelSonda[48], tStatusSonda[48];
const char* LWT = "{\"v\":1,\"deviceId\":\"" DEVICE_ID "\",\"status\":\"offline\",\"ts\":null,\"ts_sync\":false}";
unsigned long ultimaTentativaWifi = 0, ultimaTentativaMqtt = 0;
bool ntpIniciado = false;
bool rollbackPendente = false;

// ===== Tempos =====
unsigned long bootMs = 0;
unsigned long brokerCaiuEm = 1;      // != 0 → sem broker desde então (começa "sem broker")
unsigned long ultimaTelemetria = 0;  // última telemetria da sonda (qualquer)
bool telemetriaInvalida = false;     // última telemetria trouxe valido:false
unsigned long estavelDesde = 0;      // para sair de SEGURO(rede) depois de 30 s estável
unsigned long ultimoCmdManual = 0;
unsigned long ultimoEstado = 0;
bool estadoMudou = true;
String ultimoCommandId = "";

// ===== Comandos =====
String idsVistos[16];
int idxIds = 0;
String otaUrl, otaVersao, otaSha, otaCmdId;
bool otaPendente = false;

void publicarEstado();
// protótipos com valor padrão (declarados aqui para o gerador de protótipos do Arduino não duplicar)
bool publicar(const char* topico, JsonDocument& doc, bool retido = false);
void publicarAck(const char* cid, const char* fase, const char* resultado, const char* codigo,
                 const char* detalhe = nullptr);
void rejeitar(const String& cid, const char* codigo, const char* detalhe = nullptr);

// =====================================================================
// Saídas
// =====================================================================
void fimDaDose(void*) {
  // roda no contexto do esp_timer: corta as bombas mesmo que o loop esteja ocupado
  digitalWrite(PIN_BOMBA_MAIS, LOW);
  digitalWrite(PIN_BOMBA_MENOS, LOW);
  doseTerminou = true;
}

void aplicarSaidas() {
  // intertravamentos finais, independentes de quem pediu
  if (bombaMais && bombaMenos) bombaMenos = false;
  if (cooler) aquecedor = false;
  if (!nivelOk) aquecedor = false;
  digitalWrite(PIN_BOMBA_MAIS, bombaMais ? HIGH : LOW);
  digitalWrite(PIN_BOMBA_MENOS, bombaMenos ? HIGH : LOW);
  digitalWrite(PIN_RELE_AQUEC, aquecedor ? HIGH : LOW);  // HIGH = desenergizado = NC fechado = liberado
  digitalWrite(PIN_RELE_COOLER, cooler ? LOW : HIGH);    // LOW = energizado = NO fechado = ligado
}

void pararDose(bool falhou) {
  esp_timer_stop(timerDose);
  bombaMais = bombaMenos = false;
  aplicarSaidas();
  if (doseCmdId.length()) {
    if (falhou) publicarAck(doseCmdId.c_str(), "executado", "falha", "E_FALHA_EXECUCAO", "dose interrompida");
    doseCmdId = "";
  }
  doseTerminou = false;
  estadoMudou = true;
}

void entrarSeguro(const char* causa) {
  if (modo == SEGURO && causaSeguro == causa) return;
  Serial.printf("[Modo] %s -> SEGURO (causa: %s)\n", nomeModo(modo), causa);
  if (bombaMais || bombaMenos) pararDose(true);
  modo = SEGURO;
  causaSeguro = causa;
  cooler = false;
  aquecedor = true;  // relé desenergizado: aquecedor no próprio termostato (aplicarSaidas bloqueia se nível baixo)
  aplicarSaidas();
  estavelDesde = 0;
  estadoMudou = true;
}

void mudarModo(Modo m) {
  if (m == modo) return;
  Serial.printf("[Modo] %s -> %s\n", nomeModo(modo), nomeModo(m));
  modo = m;
  causaSeguro = "";
  if (m == MANUAL) ultimoCmdManual = millis();
  estadoMudou = true;
}

// =====================================================================
// Hora
// =====================================================================
bool horaValida() { return time(nullptr) > 1700000000; }

void preencherTs(JsonDocument& doc) {
  doc["v"] = 1;
  doc["deviceId"] = DEVICE_ID;
  if (horaValida()) {
    char b[24];
    time_t t = time(nullptr);
    struct tm tmv;
    gmtime_r(&t, &tmv);
    strftime(b, sizeof b, "%Y-%m-%dT%H:%M:%SZ", &tmv);
    doc["ts"] = b;
    doc["ts_sync"] = true;
  } else {
    doc["ts"] = nullptr;
    doc["ts_sync"] = false;
  }
}

time_t parseIso(const char* s) {
  struct tm t = {};
  if (!s || sscanf(s, "%d-%d-%dT%d:%d:%d", &t.tm_year, &t.tm_mon, &t.tm_mday, &t.tm_hour, &t.tm_min, &t.tm_sec) != 6)
    return 0;
  t.tm_year -= 1900;
  t.tm_mon -= 1;
  return mktime(&t);
}

// =====================================================================
// NVS
// =====================================================================
bool configNaFaixa(const Config& c) {
  return c.dose_max_ms >= 100 && c.dose_max_ms <= DOSE_LIMITE_MS && c.manual_timeout_s >= 60 &&
         c.manual_timeout_s <= 3600 && c.telemetria_timeout_s >= 10 && c.telemetria_timeout_s <= 300 &&
         c.rede_timeout_s >= 10 && c.rede_timeout_s <= 300;
}

void carregarConfig() {
  prefs.begin("cfg", true);
  cfg.dose_max_ms = prefs.getUInt("dose_max", cfg.dose_max_ms);
  cfg.manual_timeout_s = prefs.getUInt("manual_to", cfg.manual_timeout_s);
  cfg.telemetria_timeout_s = prefs.getUInt("tel_to", cfg.telemetria_timeout_s);
  cfg.rede_timeout_s = prefs.getUInt("rede_to", cfg.rede_timeout_s);
  cfg.versao = prefs.getUInt("versao", 0);
  prefs.end();
  configValida = configNaFaixa(cfg);
  Serial.printf("[NVS] config v%u %s\n", cfg.versao, configValida ? "valida" : "INVALIDA");
}

void salvarConfig() {
  prefs.begin("cfg", false);
  prefs.putUInt("dose_max", cfg.dose_max_ms);
  prefs.putUInt("manual_to", cfg.manual_timeout_s);
  prefs.putUInt("tel_to", cfg.telemetria_timeout_s);
  prefs.putUInt("rede_to", cfg.rede_timeout_s);
  prefs.putUInt("versao", cfg.versao);
  prefs.end();
}

// =====================================================================
// MQTT: publicação
// =====================================================================
bool publicar(const char* topico, JsonDocument& doc, bool retido) {
  if (!mqtt.connected()) return false;
  char buf[1024];
  size_t n = serializeJson(doc, buf, sizeof buf);
  bool ok = mqtt.publish(topico, (const uint8_t*)buf, n, retido);
  Serial.printf("[MQTT] %s %s %s\n", ok ? "->" : "FALHOU", topico, buf);
  return ok;
}

void publicarAck(const char* cid, const char* fase, const char* resultado, const char* codigo, const char* detalhe) {
  JsonDocument d;
  preencherTs(d);
  if (cid && *cid) d["commandId"] = cid; else d["commandId"] = nullptr;
  d["fase"] = fase;
  d["resultado"] = resultado;
  if (codigo) d["codigo"] = codigo; else d["codigo"] = nullptr;
  if (detalhe) d["detalhe"] = detalhe;
  publicar(tAck, d);
}

void publicarEstado() {
  JsonDocument d;
  preencherTs(d);
  d["modo"] = nomeModo(modo);
  if (modo == SEGURO) d["causa_seguro"] = causaSeguro; else d["causa_seguro"] = nullptr;
  JsonObject a = d["atuadores"].to<JsonObject>();
  a["bomba_ph_mais"] = bombaMais ? "ON" : "OFF";
  a["bomba_ph_menos"] = bombaMenos ? "ON" : "OFF";
  a["aquecedor"] = aquecedor ? "ON" : "OFF";
  a["cooler"] = cooler ? "ON" : "OFF";
  d["nivel"] = nivelOk ? "OK" : "BAIXO";
  if (ultimoCommandId.length()) d["ultimo_command_id"] = ultimoCommandId; else d["ultimo_command_id"] = nullptr;
  d["fw"] = FW_VERSAO;
  d["config_versao"] = cfg.versao;
  d["rssi_dbm"] = WiFi.RSSI();
  d["uptime_s"] = millis() / 1000;
  JsonObject c = d["config"].to<JsonObject>();
  c["dose_max_ms"] = cfg.dose_max_ms;
  c["manual_timeout_s"] = cfg.manual_timeout_s;
  c["telemetria_timeout_s"] = cfg.telemetria_timeout_s;
  c["rede_timeout_s"] = cfg.rede_timeout_s;
  if (publicar(tEstado, d, true)) {
    ultimoEstado = millis();
    estadoMudou = false;
  }
}

// =====================================================================
// Telemetria da sonda (o controlador precisa dela para sair de BOOT e para o gatilho de SEGURO)
// =====================================================================
void processarTelemetriaSonda(const uint8_t* payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, (const char*)payload, len)) return;
  JsonArray l = doc["leituras"].as<JsonArray>();
  if (l.isNull() || l.size() == 0) return;
  bool valida = true;
  for (JsonObject x : l) valida = valida && (x["valido"] | false);
  ultimaTelemetria = millis();
  if (ultimaTelemetria == 0) ultimaTelemetria = 1;
  telemetriaInvalida = !valida;
}

bool telemetriaRecente() {
  return ultimaTelemetria && millis() - ultimaTelemetria < cfg.telemetria_timeout_s * 1000UL;
}
bool sensoresValidos() { return telemetriaRecente() && !telemetriaInvalida; }

// =====================================================================
// Comandos (aquario/v1/ctrl-01/cmd) — fluxograma "Condição de intertravamento" do CP12
// =====================================================================
bool idJaVisto(const String& id) {
  for (auto& x : idsVistos) if (x == id) return true;
  idsVistos[idxIds] = id;
  idxIds = (idxIds + 1) % 16;
  return false;
}

bool numero(JsonVariant v) { return v.is<float>() || v.is<int>(); }

void rejeitar(const String& cid, const char* codigo, const char* detalhe) {
  Serial.printf("[Cmd] %s rejeitado: %s %s\n", cid.c_str(), codigo, detalhe ? detalhe : "");
  publicarAck(cid.c_str(), "recebido", "rejeitado", codigo, detalhe);
}

void concluir(const String& cid) {
  ultimoCommandId = cid;
  publicarAck(cid.c_str(), "executado", "ok", nullptr);
  estadoMudou = true;
  publicarEstado();
}

void processarComando(const uint8_t* payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, (const char*)payload, len) || !doc.is<JsonObject>()) {
    publicarAck(nullptr, "recebido", "rejeitado", "E_PAYLOAD_INVALIDO", "JSON invalido");
    return;
  }
  String cid = doc["commandId"] | "";
  if (cid.length() != 36) {
    publicarAck(nullptr, "recebido", "rejeitado", "E_PAYLOAD_INVALIDO", "commandId ausente");
    return;
  }
  if ((doc["v"] | 0) != 1) return rejeitar(cid, "E_VERSAO");
  if (idJaVisto(cid)) return rejeitar(cid, "E_DUPLICADO");
  int expira = doc["expira_em_s"] | 10;
  time_t ts = parseIso(doc["ts"] | "");
  if (horaValida() && ts && time(nullptr) > ts + expira) return rejeitar(cid, "E_EXPIRADO");

  String acao = doc["acao"] | "";
  String origem = doc["origem"] | "";
  JsonObject p = doc["params"].as<JsonObject>();
  bool atuador = acao == "dosar" || acao == "aquecedor" || acao == "cooler";
  if (!atuador && acao != "modo" && acao != "config" && acao != "ota") return rejeitar(cid, "E_ACAO_DESCONHECIDA");
  if (!(origem == "usuario" || origem == "sistema" || origem.startsWith("regra:")))
    return rejeitar(cid, "E_PAYLOAD_INVALIDO", "origem invalida");

  // ---- modo permite? ----
  if (modo == BOOT && (atuador || acao == "modo")) return rejeitar(cid, "E_INTERTRAVAMENTO", "em BOOT");
  if (modo == SEGURO && atuador) return rejeitar(cid, "E_INTERTRAVAMENTO", "em SEGURO");
  if (modo == MANUAL && (atuador || acao == "modo") && origem != "usuario")
    return rejeitar(cid, "E_INTERTRAVAMENTO", "MANUAL so aceita origem usuario");

  // ---- parâmetros + intertravamento + execução ----
  if (acao == "dosar") {
    String alvo = p["alvo"] | "";
    int dur = p["duracao_ms"] | 0;
    if ((alvo != "bomba_ph_mais" && alvo != "bomba_ph_menos") || dur < 100 || dur > DOSE_LIMITE_MS)
      return rejeitar(cid, "E_PAYLOAD_INVALIDO");
    if ((uint32_t)dur > cfg.dose_max_ms) return rejeitar(cid, "E_INTERTRAVAMENTO", "acima de dose_max_ms");
    if (bombaMais || bombaMenos) return rejeitar(cid, "E_INTERTRAVAMENTO", "outra dose em andamento");
    publicarAck(cid.c_str(), "recebido", "ok", nullptr);
    if (alvo == "bomba_ph_mais") bombaMais = true; else bombaMenos = true;
    doseCmdId = cid;
    doseTerminou = false;
    aplicarSaidas();
    esp_timer_start_once(timerDose, (uint64_t)dur * 1000ULL);  // corte garantido por timer local
    estadoMudou = true;
    publicarEstado();
    // o ack "executado" sai quando o timer cortar a bomba (loop)
  } else if (acao == "aquecedor" || acao == "cooler") {
    String e = p["estado"] | "";
    if (e != "ON" && e != "OFF") return rejeitar(cid, "E_PAYLOAD_INVALIDO");
    bool liga = e == "ON";
    if (acao == "aquecedor" && liga && cooler) return rejeitar(cid, "E_INTERTRAVAMENTO", "cooler ligado");
    if (acao == "aquecedor" && liga && !nivelOk) return rejeitar(cid, "E_INTERTRAVAMENTO", "nivel baixo");
    publicarAck(cid.c_str(), "recebido", "ok", nullptr);
    if (acao == "aquecedor") aquecedor = liga;
    else {
      if (liga) { aquecedor = false; aplicarSaidas(); }  // bloqueia o aquecedor ANTES de ligar o cooler
      cooler = liga;
    }
    aplicarSaidas();
    concluir(cid);
  } else if (acao == "modo") {
    String m = p["modo"] | "";
    if (m != "AUTO" && m != "MANUAL" && m != "SEGURO") return rejeitar(cid, "E_PAYLOAD_INVALIDO");
    if (m == "AUTO" && modo == SEGURO && (!sensoresValidos() || !mqtt.connected() || !configValida))
      return rejeitar(cid, "E_INTERTRAVAMENTO", "sensores invalidos ou config invalida");
    if (m == "MANUAL" && modo == SEGURO) return rejeitar(cid, "E_INTERTRAVAMENTO", "saia de SEGURO por AUTO");
    publicarAck(cid.c_str(), "recebido", "ok", nullptr);
    if (m == "SEGURO") entrarSeguro("comando");
    else mudarModo(m == "AUTO" ? AUTO : MANUAL);
    concluir(cid);
  } else if (acao == "config") {
    if (p.isNull()) return rejeitar(cid, "E_PAYLOAD_INVALIDO");
    Config novo = cfg;
    int n = 0;
    for (JsonPair kv : p) {
      const char* k = kv.key().c_str();
      if (!numero(kv.value())) return rejeitar(cid, "E_PAYLOAD_INVALIDO", k);
      uint32_t v = kv.value().as<uint32_t>();
      if (!strcmp(k, "dose_max_ms")) novo.dose_max_ms = v;
      else if (!strcmp(k, "manual_timeout_s")) novo.manual_timeout_s = v;
      else if (!strcmp(k, "telemetria_timeout_s")) novo.telemetria_timeout_s = v;
      else if (!strcmp(k, "rede_timeout_s")) novo.rede_timeout_s = v;
      else return rejeitar(cid, "E_PAYLOAD_INVALIDO", k);
      n++;
    }
    if (!n || !configNaFaixa(novo)) return rejeitar(cid, "E_PAYLOAD_INVALIDO", "fora da faixa");
    publicarAck(cid.c_str(), "recebido", "ok", nullptr);
    novo.versao = cfg.versao + 1;
    cfg = novo;
    configValida = true;
    salvarConfig();
    concluir(cid);
  } else if (acao == "ota") {
    String url = p["url"] | "", versao = p["versao"] | "", sha = p["sha256"] | "";
    if (!url.startsWith("http") || versao.length() == 0 || sha.length() != 64) return rejeitar(cid, "E_PAYLOAD_INVALIDO");
    publicarAck(cid.c_str(), "recebido", "ok", nullptr);
    otaUrl = url; otaVersao = versao; otaSha = sha; otaCmdId = cid;
    otaPendente = true;
  }
  if (modo == MANUAL && origem == "usuario") ultimoCmdManual = millis();
}

void aoReceber(char* topico, byte* payload, unsigned int len) {
  String t(topico);  // o buffer do PubSubClient é reutilizado ao publicar: copia antes
  static uint8_t copia[1024];
  if (len > sizeof copia) len = sizeof copia;
  memcpy(copia, payload, len);
  if (t == tCmd) processarComando(copia, len);
  else if (t == tTelSonda) processarTelemetriaSonda(copia, len);
}

// =====================================================================
// OTA (R17)
// =====================================================================
extern "C" bool verifyRollbackLater() { return true; }

bool baixarOta(String& erro) {
  HTTPClient http;
  WiFiClientSecure seguro;
  WiFiClient simples;
  bool https = otaUrl.startsWith("https");
  if (https) seguro.setCACert(MQTT_CA_CERT);
  if (!(https ? http.begin(seguro, otaUrl) : http.begin(simples, otaUrl))) { erro = "URL invalida"; return false; }
  int codigo = http.GET();
  if (codigo != 200) { erro = "HTTP " + String(codigo); http.end(); return false; }
  int total = http.getSize();
  if (total <= 0 || !Update.begin(total)) { erro = "tamanho/particao"; http.end(); return false; }

  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  mbedtls_sha256_starts(&ctx, 0);
  auto* s = http.getStreamPtr();
  uint8_t buf[1024];
  int lidos = 0;
  unsigned long ultimoDado = millis();
  while (lidos < total && millis() - ultimoDado < 15000) {
    int disp = s->available();
    if (disp <= 0) { delay(5); continue; }
    int n = s->readBytes(buf, min(disp, (int)sizeof buf));
    mbedtls_sha256_update(&ctx, buf, n);
    if (Update.write(buf, n) != (size_t)n) break;
    lidos += n;
    ultimoDado = millis();
  }
  http.end();
  uint8_t hash[32];
  mbedtls_sha256_finish(&ctx, hash);
  mbedtls_sha256_free(&ctx);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + 2 * i, "%02x", hash[i]);
  if (lidos != total) { erro = "download incompleto"; Update.abort(); return false; }
  if (otaSha != hex) { erro = "sha256 nao confere"; Update.abort(); return false; }
  if (!Update.end(true)) { erro = "Update.end falhou"; return false; }
  return true;
}

void executarOta() {
  otaPendente = false;
  // durante a atualização tudo fica no estado seguro
  if (bombaMais || bombaMenos) pararDose(true);
  cooler = false;
  aquecedor = true;
  aplicarSaidas();
  Serial.printf("[OTA] baixando %s (v%s)\n", otaUrl.c_str(), otaVersao.c_str());
  String erro;
  if (baixarOta(erro)) {
    ultimoCommandId = otaCmdId;
    publicarAck(otaCmdId.c_str(), "executado", "ok", nullptr);
    mqtt.loop();
    delay(500);
    ESP.restart();
  } else {
    Serial.println("[OTA] falhou: " + erro);
    publicarAck(otaCmdId.c_str(), "executado", "falha", "E_FALHA_EXECUCAO", erro.c_str());
    estadoMudou = true;
  }
}

// =====================================================================
// Rede sem bloqueio
// =====================================================================
void cuidarDaRede() {
  unsigned long agora = millis();
  bool conectado = mqtt.connected();
  if (conectado) brokerCaiuEm = 0;
  else if (!brokerCaiuEm) brokerCaiuEm = agora;

  if (WiFi.status() != WL_CONNECTED) {
    if (agora - ultimaTentativaWifi > 10000) {
      ultimaTentativaWifi = agora;
      Serial.println("[WiFi] tentando conectar...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_SENHA);
    }
    return;
  }
  if (!ntpIniciado) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    ntpIniciado = true;
    Serial.printf("[WiFi] conectado, IP %s\n", WiFi.localIP().toString().c_str());
  }
  if (conectado || !horaValida() || agora - ultimaTentativaMqtt < 5000) return;
  ultimaTentativaMqtt = agora;
  Serial.print("[MQTT] conectando com TLS... ");
  if (mqtt.connect(DEVICE_ID, MQTT_USUARIO, MQTT_SENHA, tStatus, 1, true, LWT)) {
    Serial.println("ok");
    brokerCaiuEm = 0;
    JsonDocument d;
    preencherTs(d);
    d["status"] = "online";
    d["fw"] = FW_VERSAO;
    publicar(tStatus, d, true);
    mqtt.subscribe(tCmd, 1);
    mqtt.subscribe(tTelSonda, 0);
    estadoMudou = true;
    if (rollbackPendente) {
      esp_ota_mark_app_valid_cancel_rollback();
      rollbackPendente = false;
      Serial.println("[OTA] nova versao validada");
    }
  } else {
    Serial.printf("falhou rc=%d\n", mqtt.state());
  }
}

// =====================================================================
// Boia (com filtro de 1 s) e máquina de estados
// =====================================================================
void cuidarDaBoia() {
  static bool leituraAnterior = true;
  static unsigned long mudouEm = 0;
  bool ok = digitalRead(PIN_BOIA) == LOW;
  if (ok != leituraAnterior) { leituraAnterior = ok; mudouEm = millis(); }
  if (ok != nivelOk && millis() - mudouEm > 1000) {
    nivelOk = ok;
    Serial.printf("[Boia] nivel %s\n", ok ? "OK" : "BAIXO");
    aplicarSaidas();  // nível baixo bloqueia o aquecedor em qualquer modo
    estadoMudou = true;
  }
}

void cuidarDoModo() {
  unsigned long agora = millis();
  bool semBroker = brokerCaiuEm && agora - brokerCaiuEm > cfg.rede_timeout_s * 1000UL;
  bool semTelemetria = !telemetriaRecente() && agora - bootMs > cfg.telemetria_timeout_s * 1000UL;

  switch (modo) {
    case BOOT:
      if (!configValida) entrarSeguro("config");
      else if (sensoresValidos() && mqtt.connected()) mudarModo(AUTO);
      else if (agora - bootMs > 30000) entrarSeguro(telemetriaInvalida ? "sensor" : "rede");
      break;
    case AUTO:
    case MANUAL:
      if (semBroker || semTelemetria) entrarSeguro("rede");
      else if (telemetriaRecente() && telemetriaInvalida) entrarSeguro("sensor");
      else if (modo == MANUAL && agora - ultimoCmdManual > cfg.manual_timeout_s * 1000UL) mudarModo(AUTO);
      break;
    case SEGURO:
      if (causaSeguro == "rede") {
        if (mqtt.connected() && sensoresValidos() && configValida) {
          if (!estavelDesde) estavelDesde = agora;
          if (agora - estavelDesde >= 30000) mudarModo(AUTO);  // volta sozinho após 30 s estável
        } else {
          estavelDesde = 0;
        }
      }
      // causa sensor/comando/config: só com comando modo=AUTO
      break;
  }
}

// =====================================================================
void setup() {
  // 1ª coisa: níveis seguros (bombas OFF, cooler OFF, aquecedor no termostato) antes de virar saída
  digitalWrite(PIN_BOMBA_MAIS, LOW);
  digitalWrite(PIN_BOMBA_MENOS, LOW);
  digitalWrite(PIN_RELE_AQUEC, HIGH);
  digitalWrite(PIN_RELE_COOLER, HIGH);
  pinMode(PIN_BOMBA_MAIS, OUTPUT);
  pinMode(PIN_BOMBA_MENOS, OUTPUT);
  pinMode(PIN_RELE_AQUEC, OUTPUT);
  pinMode(PIN_RELE_COOLER, OUTPUT);
  pinMode(PIN_BOIA, INPUT);  // GPIO34 não tem pull-up interno: R5 10 kΩ externo
  nivelOk = digitalRead(PIN_BOIA) == LOW;
  aplicarSaidas();

  Serial.begin(115200);
  Serial.printf("\n=== Aquario Inteligente - %s fw %s ===\n", DEVICE_ID, FW_VERSAO);
  bootMs = millis();

  esp_timer_create_args_t args = {};
  args.callback = &fimDaDose;
  args.name = "dose";
  esp_timer_create(&args, &timerDose);

  esp_ota_img_states_t st;
  if (esp_ota_get_state_partition(esp_ota_get_running_partition(), &st) == ESP_OK && st == ESP_OTA_IMG_PENDING_VERIFY) {
    rollbackPendente = true;
    Serial.println("[OTA] versao nova aguardando validacao (precisa conectar ao broker em 3 min)");
  }

  carregarConfig();

  snprintf(tEstado, sizeof tEstado, "aquario/v1/%s/estado", DEVICE_ID);
  snprintf(tCmd, sizeof tCmd, "aquario/v1/%s/cmd", DEVICE_ID);
  snprintf(tAck, sizeof tAck, "aquario/v1/%s/ack", DEVICE_ID);
  snprintf(tStatus, sizeof tStatus, "aquario/v1/%s/status", DEVICE_ID);
  snprintf(tTelSonda, sizeof tTelSonda, "aquario/v1/%s/telemetria", SONDA_ID);
  snprintf(tStatusSonda, sizeof tStatusSonda, "aquario/v1/%s/status", SONDA_ID);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  ultimaTentativaWifi = millis();

  net.setCACert(MQTT_CA_CERT);
  net.setHandshakeTimeout(8);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(1024);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(5);
  mqtt.setCallback(aoReceber);
}

void loop() {
  cuidarDaRede();
  mqtt.loop();
  cuidarDaBoia();
  cuidarDoModo();

  if (doseTerminou) {  // o timer cortou a bomba
    String cid = doseCmdId;
    doseCmdId = "";
    pararDose(false);
    if (cid.length()) concluir(cid);
  }
  if (otaPendente) executarOta();
  if (estadoMudou || millis() - ultimoEstado > 60000) publicarEstado();
  if (rollbackPendente && millis() > 180000) {
    Serial.println("[OTA] nova versao nao conectou: voltando para a anterior");
    esp_ota_mark_app_invalid_rollback_and_reboot();
  }
}
