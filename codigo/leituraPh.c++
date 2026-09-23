#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <HTTPClient.h>

// Credenciais do Wi-Fi e IP do servidor ficam fora do repositório.
// Copie "secrets.example.h" para "secrets.h" e preencha com os seus dados.
#include "secrets.h"

#define PH_PIN 35
#define NUM_SAMPLES 15

// ===== Divisor de tensão no pino do pH =====
// O PH-4502C alimentado em 5 V pode entregar até 5 V no Po, mas o ADC do ESP32
// só lê até ~3,1 V (acima disso a leitura trava no máximo e o pH fica fixo).
// Divisor: Po -> R1 -> GPIO35 -> R2 -> GND.  FATOR = (R1 + R2) / R2
// Sem divisor: 1.0  |  10k/10k: 2.0  |  10k/20k: 1.5
#define FATOR_DIVISOR 2.0
#define MV_SATURADO 3100   // acima disso o ADC do ESP32 não mede mais

// ===== Atuador =====
// LED embutido da placa ESP32 DevKit (GPIO 2). Não exige nenhuma ligação nova
// no circuito. Ele é o atuador do sistema e SÓ é acionado por comando MQTT.
#define ATUADOR_PIN 2

// ===== OLED =====
#define SCREEN_WIDTH   128
#define SCREEN_HEIGHT  64
#define OLED_RESET     -1
#define SCREEN_ADDRESS 0x3C   // se não aparecer nada, tente 0x3D

#define I2C_SDA 21
#define I2C_SCL 22

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ===== MQTT =====
const char* mqtt_server     = "test.mosquitto.org";
// 1883 é bloqueada nesta rede; 8883 = MQTT com TLS (mesma porta do servidor)
const int   mqtt_port       = 8883;
// Prefixo único para não colidir com outras equipes no broker público
const char* topico_ph       = "sistema/aquario/ph";        // ESP32 PUBLICA a leitura
const char* topico_atuador  = "sistema/aquario/atuador";   // ESP32 ASSINA o comando

WiFiClientSecure espClient;
PubSubClient client(espClient);

// ===== Calibração do pH =====
// pH = PH_SLOPE * tensao + PH_OFFSET
float PH_SLOPE  = -5.70;
float PH_OFFSET = 21.34;

int buffer_arr[NUM_SAMPLES];

// Estado do atuador: muda SOMENTE dentro do callback MQTT
bool atuadorLigado = false;

// Controle de tempo sem travar o loop (para receber comandos rapidamente)
const unsigned long INTERVALO_LEITURA_MS = 1000;
const unsigned long INTERVALO_RECONEXAO_MS = 2000;
unsigned long ultimaLeitura = 0;
unsigned long ultimaTentativaMQTT = 0;

// Última leitura, para redesenhar o OLED quando chega um comando
float ultimaTensao = 0;
float ultimoPh = 0;
bool adcSaturado = false;

// ---------------------------------------------------------
// Conecta ao WiFi mostrando o progresso no Serial e no OLED
// ---------------------------------------------------------
void conectarWiFi()
{
  Serial.print("Conectando ao WiFi");
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Conectando ao WiFi");
  display.println(WIFI_SSID);
  display.display();

  WiFi.begin(WIFI_SSID, WIFI_SENHA);

  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 40) // ~20s de timeout
  {
    delay(500);
    Serial.print(".");
    display.print(".");
    display.display();
    tentativas++;
  }

  display.clearDisplay();
  display.setCursor(0, 0);

  if (WiFi.status() == WL_CONNECTED)
  {
    Serial.println("\nConectado!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());

    display.println("WiFi conectado!");
    display.println(WiFi.localIP());
  }
  else
  {
    Serial.println("\nFalha ao conectar ao WiFi.");
    Serial.println("Continuando sem WiFi...");

    display.println("Falha no WiFi.");
    display.println("Continuando offline");
  }

  display.display();
  delay(1500);
}

void mostrarNoOLED(float tensao, float ph)
{
  display.clearDisplay();

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("Monitor de pH  ");
  display.println(WiFi.status() == WL_CONNECTED ? "\n[WiFi On]" : "\n[WiFi Off]");
  display.drawLine(0, 10, SCREEN_WIDTH, 10, SSD1306_WHITE);

  display.setCursor(0, 18);
  display.print("Tensao: ");
  display.print(tensao, 3);
  display.println(" V");

  display.setTextSize(2);
  display.setCursor(0, 34);
  display.print("pH ");
  display.print(ph, 2);

  // Estado do atuador, conforme o último comando recebido via MQTT
  display.setTextSize(1);
  display.setCursor(0, 54);
  display.print("Atuador (MQTT): ");
  display.print(atuadorLigado ? "ON" : "OFF");

  display.display();
}

// ---------------------------------------------------------
// Callback MQTT: ÚNICO lugar do firmware que aciona o atuador.
// O comando vem do servidor, que assinou a leitura publicada.
// ---------------------------------------------------------
void aoReceberMensagem(char* topico, byte* payload, unsigned int tamanho)
{
  String mensagem;
  for (unsigned int i = 0; i < tamanho; i++)
    mensagem += (char)payload[i];
  mensagem.trim();
  mensagem.toUpperCase();

  Serial.print("Comando recebido em [");
  Serial.print(topico);
  Serial.print("]: ");
  Serial.println(mensagem);

  if (String(topico) != topico_atuador) return;

  if (mensagem == "ON")
  {
    atuadorLigado = true;
    digitalWrite(ATUADOR_PIN, HIGH);
  }
  else if (mensagem == "OFF")
  {
    atuadorLigado = false;
    digitalWrite(ATUADOR_PIN, LOW);
  }
  else
  {
    Serial.println("Comando desconhecido, ignorado.");
    return;
  }

  mostrarNoOLED(ultimaTensao, ultimoPh);
}

// Tenta reconectar ao broker sem travar o loop
void reconectarMQTT()
{
  if (WiFi.status() != WL_CONNECTED) return; // sem WiFi não adianta tentar
  if (client.connected()) return;

  unsigned long agora = millis();
  if (agora - ultimaTentativaMQTT < INTERVALO_RECONEXAO_MS) return;
  ultimaTentativaMQTT = agora;

  Serial.print("Conectando ao broker MQTT...");
  String clientId = "ESP32-pH-" + String(random(0xffff), HEX);
  if (client.connect(clientId.c_str()))
  {
    Serial.println("conectado!");
    // Assina o tópico de comando a cada (re)conexão
    client.subscribe(topico_atuador);
    Serial.print("Assinado: ");
    Serial.println(topico_atuador);
  }
  else
  {
    Serial.print("falhou, rc=");
    Serial.print(client.state());
    Serial.println(" tentando de novo em 2s");
  }
}

void setup()
{
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("================================");
  Serial.println("   MONITOR DE PH - PH-4502C");
  Serial.println("================================");

  // Atuador começa desligado e só muda por comando MQTT
  pinMode(ATUADOR_PIN, OUTPUT);
  digitalWrite(ATUADOR_PIN, LOW);

  analogReadResolution(12);
  analogSetPinAttenuation(PH_PIN, ADC_11db);

  // Inicializa I2C nos pinos padrão da ESP32
  Wire.begin(I2C_SDA, I2C_SCL);

  if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS))
  {
    Serial.println("Falha ao iniciar o display OLED!");
    while (1) delay(10);
  }

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Monitor de pH");
  display.println("Iniciando...");
  display.display();

  delay(1500);

  WiFi.mode(WIFI_STA);   // evita instabilidade em hardware real
  conectarWiFi();

  randomSeed(micros());
  espClient.setInsecure();   // broker público de teste: criptografa sem validar certificado
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(aoReceberMensagem);

  Serial.println("Iniciando leitura...\n");
}

float lerTensaoFiltrada()
{
  for (int i = 0; i < NUM_SAMPLES; i++)
  {
    // analogReadMilliVolts usa a calibração de fábrica do ESP32 (mais preciso
    // que analogRead * 3.3 / 4095, que não é linear)
    buffer_arr[i] = analogReadMilliVolts(PH_PIN);
    delay(20);
  }

  for (int i = 0; i < NUM_SAMPLES - 1; i++)
    for (int j = i + 1; j < NUM_SAMPLES; j++)
      if (buffer_arr[i] > buffer_arr[j])
      {
        int temp      = buffer_arr[i];
        buffer_arr[i] = buffer_arr[j];
        buffer_arr[j] = temp;
      }

  long soma = 0;
  int inicio = NUM_SAMPLES / 4;
  int fim    = NUM_SAMPLES - inicio;
  int qtd    = fim - inicio;

  for (int i = inicio; i < fim; i++)
    soma += buffer_arr[i];

  float mvMedio = (float)soma / qtd;
  adcSaturado = mvMedio >= MV_SATURADO;

  Serial.print("Pino: ");
  Serial.print(mvMedio, 0);
  Serial.print(" mV   |   ");

  // Tensão no pino convertida de volta para a tensão real do Po do módulo
  return mvMedio / 1000.0 * FATOR_DIVISOR;
}

void publicarMQTT(float tensao, float ph)
{
  if (!client.connected()) return;
  String payload = "{\"ph\":" + String(ph, 2) + ",\"tensao\":" + String(tensao, 3) + "}";
  client.publish(topico_ph, payload.c_str());
  Serial.println("Publicado no MQTT: " + payload);
}

// Envio HTTP mantido apenas para o dashboard web (histórico).
// O comando ao atuador NÃO passa por aqui.
void enviarLeitura(float ph, float tensao)
{
    if (WiFi.status() != WL_CONNECTED)
        return;

    HTTPClient http;
    http.begin(SERVIDOR_URL);
    http.addHeader("Content-Type", "application/json");

    String payload = "{\"ph\":" + String(ph, 2) +
                     ",\"voltage\":" + String(tensao, 3) +
                     ",\"device\":\"esp32-ph01\"}";

    int codigo = http.POST(payload);

    Serial.printf("POST enviado, resposta HTTP: %d\n", codigo);

    http.end();
}

void loop()
{
  // Tenta reconectar automaticamente caso a conexão caia
  if (WiFi.status() != WL_CONNECTED)
  {
    Serial.println("WiFi desconectado. Tentando reconectar...");
    conectarWiFi();
  }

  reconectarMQTT();
  client.loop(); // processa comandos recebidos no tópico do atuador

  unsigned long agora = millis();
  if (agora - ultimaLeitura < INTERVALO_LEITURA_MS) return;
  ultimaLeitura = agora;

  float tensao = lerTensaoFiltrada();
  float ph = PH_SLOPE * tensao + PH_OFFSET;
  ultimaTensao = tensao;
  ultimoPh = ph;

  Serial.print("Tensao: ");
  Serial.print(tensao, 3);
  Serial.print(" V   |   pH: ");
  Serial.println(ph, 2);
  if (adcSaturado)
    Serial.println("AVISO: ADC saturado (tensao >= ~3,1 V no pino). Verifique o divisor/offset do modulo.");

  publicarMQTT(tensao, ph);   // 1) leitura sai pela rede via MQTT
  enviarLeitura(ph, tensao);  // 2) cópia para o dashboard (HTTP)
  mostrarNoOLED(tensao, ph);
  // Nenhuma decisão sobre o atuador é tomada aqui: ela vem do servidor.
}
