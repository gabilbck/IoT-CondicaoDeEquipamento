/*
 * Aquário Inteligente — firmware da SONDA (sonda-01)
 * pH (PH-4502C, GPIO35 via divisor 10k/10k) + temperatura (DS18B20, GPIO4) + OLED SSD1306 + buzzer (GPIO25 via BC547)
 *
 * - Leitura sem bloqueio (millis), validada (faixa plausível e valores-sentinela).
 * - Regra local que funciona sem rede: NORMAL / ALERTA_LOCAL / FALHA_SENSOR (buzzer + OLED).
 * - MQTT com TLS validado pela CA própria, usuário/senha, Last Will, contrato v1 (CONTRATOS.md).
 * - Configuração na NVS (faixas críticas, calibração, intervalos), alterável por comando "config".
 * - Hora por NTP (ts_sync), OTA por comando "ota" com verificação de sha256 e rollback.
 *
 * Bibliotecas: PubSubClient, ArduinoJson (v7), OneWire, DallasTemperature, Adafruit SSD1306, Adafruit GFX.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Update.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <time.h>
#include "esp_ota_ops.h"
#include "mbedtls/sha256.h"

#include "secrets.h"

#define FW_VERSAO "1.0.0"   // aumente antes de exportar um binário para OTA
#define DEVICE_ID "sonda-01"

// ===== Pinos (docs/hardware/mapa_de_pinos.md) =====
#define PIN_PH      35   // ADC1_CH7 (ADC2 não funciona com Wi-Fi)
#define PIN_DS18B20  4
#define PIN_BUZZER  25   // base do BC547 via 1 kΩ — HIGH = toca
#define I2C_SDA     21
#define I2C_SCL     22

// ===== pH =====
#define NUM_AMOSTRAS   15
#define FATOR_DIVISOR  2.0f     // 10k/10k
#define MV_SATURADO    3100     // acima disso o ADC do ESP32 não mede mais

// ===== OLED =====
Adafruit_SSD1306 display(128, 64, &Wire, -1);
bool oledOk = false;

// ===== Configuração (NVS) =====
struct Config {
  float ph_crit_min = 6.0, ph_crit_max = 8.0;
  float temp_crit_min = 22.0, temp_crit_max = 30.0;
  float ph_slope = -5.70, ph_offset = 21.34;
  uint32_t intervalo_ph_ms = 2000, intervalo_temp_ms = 5000;
  uint32_t versao = 0;
} cfg;
Preferences prefs;

// ===== Rede =====
WiFiClientSecure net;
PubSubClient mqtt(net);
char tTelemetria[48], tEstado[48], tCmd[48], tAck[48], tStatus[48];
const char* LWT = "{\"v\":1,\"deviceId\":\"" DEVICE_ID "\",\"status\":\"offline\",\"ts\":null,\"ts_sync\":false}";
unsigned long ultimaTentativaWifi = 0, ultimaTentativaMqtt = 0;
bool ntpIniciado = false;
bool rollbackPendente = false;

// ===== Leituras =====
int amostras[NUM_AMOSTRAS];
int nAmostras = 0;
unsigned long ultimaAmostra = 0, inicioLotePh = 0, ultimoLotePh = 0;
bool coletandoPh = false;

float ph = NAN, tensaoPh = NAN, temp = NAN;
bool phValido = false, tempValido = false;
bool temperaturaPedida = false;
unsigned long pedidoTemp = 0, ultimaTemp = 0;
OneWire oneWire(PIN_DS18B20);
DallasTemperature ds(&oneWire);

// ===== Regra local =====
enum EstadoLocal { NORMAL, ALERTA_LOCAL, FALHA_SENSOR };
EstadoLocal estadoLocal = NORMAL;
int foraSeguidas = 0, validasSeguidas = 0;
unsigned long silenciadoAte = 0;
uint32_t seq = 0;
unsigned long ultimoEstado = 0;
bool estadoMudou = true;
String ultimoCommandId = "";

// ===== Comandos =====
String idsVistos[16];
int idxIds = 0;
String otaUrl, otaVersao, otaSha, otaCmdId;
bool otaPendente = false;

void avaliarRegraLocal();
// protótipos com valor padrão (declarados aqui para o gerador de protótipos do Arduino não duplicar)
bool publicar(const char* topico, JsonDocument& doc, bool retido = false);
void publicarAck(const char* cid, const char* fase, const char* resultado, const char* codigo,
                 const char* detalhe = nullptr);

const char* nomeEstado(EstadoLocal e) {
  return e == NORMAL ? "NORMAL" : e == ALERTA_LOCAL ? "ALERTA_LOCAL" : "FALHA_SENSOR";
}

// =====================================================================
// Hora (NTP)
// =====================================================================
bool horaValida() { return time(nullptr) > 1700000000; }

void agoraIso(char* buf, size_t n) {
  time_t t = time(nullptr);
  struct tm tmv;
  gmtime_r(&t, &tmv);
  strftime(buf, n, "%Y-%m-%dT%H:%M:%SZ", &tmv);
}

void preencherTs(JsonDocument& doc) {
  doc["v"] = 1;
  doc["deviceId"] = DEVICE_ID;
  if (horaValida()) {
    char b[24];
    agoraIso(b, sizeof b);
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
  return mktime(&t);  // TZ = UTC (configTime(0, 0, ...))
}

// =====================================================================
// NVS
// =====================================================================
void carregarConfig() {
  prefs.begin("cfg", true);
  cfg.ph_crit_min = prefs.getFloat("ph_crit_min", cfg.ph_crit_min);
  cfg.ph_crit_max = prefs.getFloat("ph_crit_max", cfg.ph_crit_max);
  cfg.temp_crit_min = prefs.getFloat("temp_crit_min", cfg.temp_crit_min);
  cfg.temp_crit_max = prefs.getFloat("temp_crit_max", cfg.temp_crit_max);
  cfg.ph_slope = prefs.getFloat("ph_slope", cfg.ph_slope);
  cfg.ph_offset = prefs.getFloat("ph_offset", cfg.ph_offset);
  cfg.intervalo_ph_ms = prefs.getUInt("int_ph", cfg.intervalo_ph_ms);
  cfg.intervalo_temp_ms = prefs.getUInt("int_temp", cfg.intervalo_temp_ms);
  cfg.versao = prefs.getUInt("versao", 0);
  prefs.end();
  Serial.printf("[NVS] config v%u: pH crit %.1f-%.1f, temp crit %.1f-%.1f, slope %.3f offset %.3f\n", cfg.versao,
                cfg.ph_crit_min, cfg.ph_crit_max, cfg.temp_crit_min, cfg.temp_crit_max, cfg.ph_slope, cfg.ph_offset);
}

void salvarConfig() {
  prefs.begin("cfg", false);
  prefs.putFloat("ph_crit_min", cfg.ph_crit_min);
  prefs.putFloat("ph_crit_max", cfg.ph_crit_max);
  prefs.putFloat("temp_crit_min", cfg.temp_crit_min);
  prefs.putFloat("temp_crit_max", cfg.temp_crit_max);
  prefs.putFloat("ph_slope", cfg.ph_slope);
  prefs.putFloat("ph_offset", cfg.ph_offset);
  prefs.putUInt("int_ph", cfg.intervalo_ph_ms);
  prefs.putUInt("int_temp", cfg.intervalo_temp_ms);
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

int silenciadoRestante() {
  long r = (long)(silenciadoAte - millis());
  return silenciadoAte && r > 0 ? r / 1000 : 0;
}

void publicarEstado() {
  JsonDocument d;
  preencherTs(d);
  d["estado_local"] = nomeEstado(estadoLocal);
  d["silenciado_s"] = silenciadoRestante();
  if (ultimoCommandId.length()) d["ultimo_command_id"] = ultimoCommandId; else d["ultimo_command_id"] = nullptr;
  d["fw"] = FW_VERSAO;
  d["config_versao"] = cfg.versao;
  d["rssi_dbm"] = WiFi.RSSI();
  d["uptime_s"] = millis() / 1000;
  JsonObject c = d["config"].to<JsonObject>();
  c["ph_crit_min"] = cfg.ph_crit_min;
  c["ph_crit_max"] = cfg.ph_crit_max;
  c["temp_crit_min"] = cfg.temp_crit_min;
  c["temp_crit_max"] = cfg.temp_crit_max;
  c["ph_slope"] = cfg.ph_slope;
  c["ph_offset"] = cfg.ph_offset;
  c["intervalo_ph_ms"] = cfg.intervalo_ph_ms;
  c["intervalo_temp_ms"] = cfg.intervalo_temp_ms;
  if (publicar(tEstado, d, true)) {
    ultimoEstado = millis();
    estadoMudou = false;
  }
}

void publicarTelemetria() {
  JsonDocument d;
  preencherTs(d);
  d["seq"] = seq++;
  JsonArray l = d["leituras"].to<JsonArray>();
  JsonObject p = l.add<JsonObject>();
  p["grandeza"] = "ph";
  if (isnan(ph)) p["valor"] = nullptr; else p["valor"] = roundf(ph * 100) / 100;
  p["unidade"] = "pH";
  p["valido"] = phValido;
  if (!isnan(tensaoPh)) p["tensao_v"] = roundf(tensaoPh * 1000) / 1000;
  JsonObject t = l.add<JsonObject>();
  t["grandeza"] = "temperatura";
  if (isnan(temp)) t["valor"] = nullptr; else t["valor"] = roundf(temp * 10) / 10;
  t["unidade"] = "°C";
  t["valido"] = tempValido;
  d["estado_local"] = nomeEstado(estadoLocal);
  publicar(tTelemetria, d);
}

// =====================================================================
// Comandos (aquario/v1/sonda-01/cmd)
// =====================================================================
bool idJaVisto(const String& id) {
  for (auto& x : idsVistos) if (x == id) return true;
  idsVistos[idxIds] = id;
  idxIds = (idxIds + 1) % 16;
  return false;
}

bool numero(JsonVariant v) { return v.is<float>() || v.is<int>(); }

bool aplicarConfig(JsonObject p, String& erro) {
  Config novo = cfg;
  int n = 0;
  for (JsonPair kv : p) {
    const char* k = kv.key().c_str();
    JsonVariant v = kv.value();
    if (!numero(v)) { erro = String(k) + " deve ser numero"; return false; }
    float f = v.as<float>();
    auto faixa = [&](float lo, float hi) { if (f < lo || f > hi) { erro = String(k) + " fora da faixa"; return false; } return true; };
    if (!strcmp(k, "ph_crit_min")) { if (!faixa(0, 14)) return false; novo.ph_crit_min = f; }
    else if (!strcmp(k, "ph_crit_max")) { if (!faixa(0, 14)) return false; novo.ph_crit_max = f; }
    else if (!strcmp(k, "temp_crit_min")) { if (!faixa(0, 45)) return false; novo.temp_crit_min = f; }
    else if (!strcmp(k, "temp_crit_max")) { if (!faixa(0, 45)) return false; novo.temp_crit_max = f; }
    else if (!strcmp(k, "ph_slope")) { if (!faixa(-20, 20)) return false; novo.ph_slope = f; }
    else if (!strcmp(k, "ph_offset")) { if (!faixa(-50, 50)) return false; novo.ph_offset = f; }
    else if (!strcmp(k, "intervalo_ph_ms")) { if (!faixa(1000, 60000)) return false; novo.intervalo_ph_ms = f; }
    else if (!strcmp(k, "intervalo_temp_ms")) { if (!faixa(2000, 60000)) return false; novo.intervalo_temp_ms = f; }
    else { erro = String("chave desconhecida: ") + k; return false; }
    n++;
  }
  if (!n) { erro = "config vazia"; return false; }
  if (novo.ph_crit_min >= novo.ph_crit_max || novo.temp_crit_min >= novo.temp_crit_max) {
    erro = "min deve ser menor que max";
    return false;
  }
  novo.versao = cfg.versao + 1;
  cfg = novo;
  salvarConfig();
  return true;
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
  if ((doc["v"] | 0) != 1) { publicarAck(cid.c_str(), "recebido", "rejeitado", "E_VERSAO"); return; }
  if (idJaVisto(cid)) { publicarAck(cid.c_str(), "recebido", "rejeitado", "E_DUPLICADO"); return; }
  int expira = doc["expira_em_s"] | 10;
  time_t ts = parseIso(doc["ts"] | "");
  if (horaValida() && ts && time(nullptr) > ts + expira) {
    publicarAck(cid.c_str(), "recebido", "rejeitado", "E_EXPIRADO");
    return;
  }
  String acao = doc["acao"] | "";
  JsonObject p = doc["params"].as<JsonObject>();

  if (acao == "silenciar") {
    int s = p["duracao_s"] | 0;
    if (s < 60 || s > 3600) { publicarAck(cid.c_str(), "recebido", "rejeitado", "E_PAYLOAD_INVALIDO", "duracao_s 60-3600"); return; }
    publicarAck(cid.c_str(), "recebido", "ok", nullptr);
    silenciadoAte = millis() + (unsigned long)s * 1000UL;
    digitalWrite(PIN_BUZZER, LOW);
    ultimoCommandId = cid;
    publicarAck(cid.c_str(), "executado", "ok", nullptr);
    publicarEstado();
  } else if (acao == "config") {
    String erro;
    if (p.isNull() || !aplicarConfig(p, erro)) {
      publicarAck(cid.c_str(), "recebido", "rejeitado", "E_PAYLOAD_INVALIDO", erro.c_str());
      return;
    }
    publicarAck(cid.c_str(), "recebido", "ok", nullptr);
    ultimoCommandId = cid;
    publicarAck(cid.c_str(), "executado", "ok", nullptr);
    publicarEstado();
  } else if (acao == "ota") {
    String url = p["url"] | "", versao = p["versao"] | "", sha = p["sha256"] | "";
    if (!url.startsWith("http") || versao.length() == 0 || sha.length() != 64) {
      publicarAck(cid.c_str(), "recebido", "rejeitado", "E_PAYLOAD_INVALIDO");
      return;
    }
    publicarAck(cid.c_str(), "recebido", "ok", nullptr);
    otaUrl = url; otaVersao = versao; otaSha = sha; otaCmdId = cid;
    otaPendente = true;  // executado fora do callback
  } else {
    publicarAck(cid.c_str(), "recebido", "rejeitado", "E_ACAO_DESCONHECIDA");
  }
}

void aoReceber(char* topico, byte* payload, unsigned int len) {
  // o buffer do PubSubClient é reutilizado ao publicar: copia antes
  String t(topico);
  static uint8_t copia[1024];
  if (len > sizeof copia) len = sizeof copia;
  memcpy(copia, payload, len);
  if (t == tCmd) processarComando(copia, len);
}

// =====================================================================
// OTA (R17): download http/https, confere sha256, grava na outra partição e reinicia
// =====================================================================
extern "C" bool verifyRollbackLater() { return true; }  // a nova versão só é validada depois de conectar

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
  Serial.printf("[OTA] baixando %s (v%s)\n", otaUrl.c_str(), otaVersao.c_str());
  if (oledOk) {
    display.clearDisplay(); display.setTextSize(1); display.setCursor(0, 0);
    display.println("Atualizando firmware"); display.println(otaVersao); display.display();
  }
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
  }
}

// =====================================================================
// Rede sem bloqueio: Wi-Fi, NTP, MQTT
// =====================================================================
void cuidarDaRede() {
  unsigned long agora = millis();
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
  if (mqtt.connected()) return;
  if (!horaValida()) return;  // TLS precisa da hora certa para validar o certificado
  if (agora - ultimaTentativaMqtt < 5000) return;
  ultimaTentativaMqtt = agora;
  Serial.print("[MQTT] conectando com TLS... ");
  if (mqtt.connect(DEVICE_ID, MQTT_USUARIO, MQTT_SENHA, tStatus, 1, true, LWT)) {
    Serial.println("ok");
    JsonDocument d;
    preencherTs(d);
    d["status"] = "online";
    d["fw"] = FW_VERSAO;
    publicar(tStatus, d, true);
    mqtt.subscribe(tCmd, 1);
    publicarEstado();
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
// Sensores sem bloqueio
// =====================================================================
void cuidarDoPh() {
  unsigned long agora = millis();
  if (!coletandoPh) {
    if (agora - ultimoLotePh < cfg.intervalo_ph_ms) return;
    coletandoPh = true;
    nAmostras = 0;
    inicioLotePh = agora;
  }
  if (agora - ultimaAmostra < 20) return;  // 1 amostra a cada 20 ms
  ultimaAmostra = agora;
  amostras[nAmostras++] = analogReadMilliVolts(PIN_PH);
  if (nAmostras < NUM_AMOSTRAS) return;

  coletandoPh = false;
  ultimoLotePh = inicioLotePh;
  // ordena e faz a média da parte central (herdado da N1)
  for (int i = 0; i < NUM_AMOSTRAS - 1; i++)
    for (int j = i + 1; j < NUM_AMOSTRAS; j++)
      if (amostras[i] > amostras[j]) { int t = amostras[i]; amostras[i] = amostras[j]; amostras[j] = t; }
  long soma = 0;
  int ini = NUM_AMOSTRAS / 4, fim = NUM_AMOSTRAS - ini;
  for (int i = ini; i < fim; i++) soma += amostras[i];
  float mv = (float)soma / (fim - ini);
  bool saturado = mv >= MV_SATURADO;
  tensaoPh = mv / 1000.0f * FATOR_DIVISOR;
  ph = cfg.ph_slope * tensaoPh + cfg.ph_offset;
  phValido = !saturado && ph >= 0 && ph <= 14;
  if (saturado) Serial.println("[pH] ADC saturado (>= 3,1 V no pino): leitura invalida");

  avaliarRegraLocal();
  publicarTelemetria();
}

void cuidarDaTemperatura() {
  unsigned long agora = millis();
  if (!temperaturaPedida) {
    if (ultimaTemp && agora - ultimaTemp < cfg.intervalo_temp_ms) return;
    ds.requestTemperatures();  // não bloqueia (setWaitForConversion(false))
    temperaturaPedida = true;
    pedidoTemp = agora;
    return;
  }
  if (agora - pedidoTemp < 800) return;  // conversão de 12 bits: 750 ms
  temperaturaPedida = false;
  ultimaTemp = agora;
  float t = ds.getTempCByIndex(0);
  temp = t;
  tempValido = t != DEVICE_DISCONNECTED_C && t >= 0 && t <= 45;
  if (!tempValido) Serial.printf("[Temp] leitura invalida: %.1f\n", t);
}

// =====================================================================
// Regra local: NORMAL / ALERTA_LOCAL / FALHA_SENSOR
// =====================================================================
void mudarEstado(EstadoLocal e) {
  if (e == estadoLocal) return;
  Serial.printf("[Regra] %s -> %s\n", nomeEstado(estadoLocal), nomeEstado(e));
  estadoLocal = e;
  estadoMudou = true;
  if (e != ALERTA_LOCAL) digitalWrite(PIN_BUZZER, LOW);
}

void avaliarRegraLocal() {
  bool invalida = !phValido || (ultimaTemp && !tempValido);
  if (invalida) {
    validasSeguidas = 0;
    foraSeguidas = 0;
    mudarEstado(FALHA_SENSOR);
    return;
  }
  bool foraCritico = ph < cfg.ph_crit_min || ph > cfg.ph_crit_max ||
                     (tempValido && (temp < cfg.temp_crit_min || temp > cfg.temp_crit_max));
  bool dentroComHisterese = ph >= cfg.ph_crit_min + 0.1 && ph <= cfg.ph_crit_max - 0.1 &&
                            (!tempValido || (temp >= cfg.temp_crit_min + 0.5 && temp <= cfg.temp_crit_max - 0.5));
  switch (estadoLocal) {
    case FALHA_SENSOR:
      if (++validasSeguidas >= 5) { foraSeguidas = 0; mudarEstado(NORMAL); }
      break;
    case NORMAL:
      foraSeguidas = foraCritico ? foraSeguidas + 1 : 0;
      if (foraSeguidas >= 3) mudarEstado(ALERTA_LOCAL);
      break;
    case ALERTA_LOCAL:
      if (dentroComHisterese) { foraSeguidas = 0; mudarEstado(NORMAL); }
      break;
  }
}

void cuidarDoBuzzer() {
  bool tocar = estadoLocal == ALERTA_LOCAL && silenciadoRestante() == 0;
  if (!tocar) { digitalWrite(PIN_BUZZER, LOW); return; }
  digitalWrite(PIN_BUZZER, (millis() % 1000) < 200 ? HIGH : LOW);  // bipe intermitente
}

void cuidarDoOled() {
  static unsigned long ultimo = 0;
  if (!oledOk || millis() - ultimo < 500) return;
  ultimo = millis();
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(DEVICE_ID);
  display.print(WiFi.status() == WL_CONNECTED ? " W" : " -");
  display.print(mqtt.connected() ? " M" : " -");
  display.print(horaValida() ? " T" : " -");
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  bool alerta = estadoLocal == ALERTA_LOCAL;
  bool phFora = phValido && (ph < cfg.ph_crit_min || ph > cfg.ph_crit_max);
  bool tFora = tempValido && (temp < cfg.temp_crit_min || temp > cfg.temp_crit_max);

  display.setTextSize(2);
  display.setCursor(0, 14);
  if (alerta && phFora && (millis() / 500) % 2) display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
  if (phValido) { display.print("pH "); display.print(ph, 2); } else display.print("pH ERRO");
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 34);
  if (alerta && tFora && (millis() / 500) % 2) display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
  if (tempValido) { display.print(temp, 1); display.print(" C"); } else display.print("T ERRO");
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 55);
  display.print(nomeEstado(estadoLocal));
  if (silenciadoRestante()) display.print(" (mudo)");
  display.display();
}

// =====================================================================
void setup() {
  // 1ª coisa: buzzer mudo
  digitalWrite(PIN_BUZZER, LOW);
  pinMode(PIN_BUZZER, OUTPUT);

  Serial.begin(115200);
  Serial.printf("\n=== Aquario Inteligente - %s fw %s ===\n", DEVICE_ID, FW_VERSAO);

  esp_ota_img_states_t st;
  if (esp_ota_get_state_partition(esp_ota_get_running_partition(), &st) == ESP_OK && st == ESP_OTA_IMG_PENDING_VERIFY) {
    rollbackPendente = true;
    Serial.println("[OTA] versao nova aguardando validacao (precisa conectar ao broker em 3 min)");
  }

  carregarConfig();
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_PH, ADC_11db);
  ds.begin();
  ds.setResolution(12);
  ds.setWaitForConversion(false);

  Wire.begin(I2C_SDA, I2C_SCL);
  oledOk = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (!oledOk) Serial.println("[OLED] nao encontrado (segue sem display)");

  snprintf(tTelemetria, sizeof tTelemetria, "aquario/v1/%s/telemetria", DEVICE_ID);
  snprintf(tEstado, sizeof tEstado, "aquario/v1/%s/estado", DEVICE_ID);
  snprintf(tCmd, sizeof tCmd, "aquario/v1/%s/cmd", DEVICE_ID);
  snprintf(tAck, sizeof tAck, "aquario/v1/%s/ack", DEVICE_ID);
  snprintf(tStatus, sizeof tStatus, "aquario/v1/%s/status", DEVICE_ID);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  ultimaTentativaWifi = millis();

  net.setCACert(MQTT_CA_CERT);  // valida o broker pela CA própria (sem setInsecure)
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
  cuidarDoPh();
  cuidarDaTemperatura();
  cuidarDoBuzzer();
  cuidarDoOled();
  if (estadoMudou || millis() - ultimoEstado > 60000) publicarEstado();
  if (otaPendente) executarOta();
  if (rollbackPendente && millis() > 180000) {
    Serial.println("[OTA] nova versao nao conectou: voltando para a anterior");
    esp_ota_mark_app_invalid_rollback_and_reboot();
  }
}
