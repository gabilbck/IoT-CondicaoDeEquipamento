#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <HTTPClient.h>

#define PH_PIN 35
#define NUM_SAMPLES 15

// ===== OLED =====
#define SCREEN_WIDTH   128
#define SCREEN_HEIGHT  64
#define OLED_RESET     -1
#define SCREEN_ADDRESS 0x3C   // se não aparecer nada, tente 0x3D

#define I2C_SDA 21
#define I2C_SCL 22

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ===== WiFi =====
// IMPORTANTE: agora é hardware real (não mais o simulador Wokwi),
// então troque pelos dados da sua rede de verdade.
// A ESP32 só conecta em redes 2.4GHz (não funciona em 5GHz).
const char* ssid  = "iPhone";
const char* senha = "euamopizza";

// ===== MQTT =====
const char* mqtt_server = "test.mosquitto.org";
const int   mqtt_port   = 1883;
const char* topico_ph   = "aquario/ph";
const char* SERVIDOR_URL = "http://172.20.10.4:8000/api/ph"; // IP da máquina rodando o Docker

WiFiClient espClient;
PubSubClient client(espClient);

// ===== Calibração do pH =====
// pH = PH_SLOPE * tensao + PH_OFFSET
float PH_SLOPE  = -5.70;
float PH_OFFSET = 21.34;

int buffer_arr[NUM_SAMPLES];

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
  display.println(ssid);
  display.display();

  WiFi.begin(ssid, senha);

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

void reconectarMQTT()
{
  if (WiFi.status() != WL_CONNECTED) return; // sem WiFi não adianta tentar

  while (!client.connected())
  {
    Serial.print("Conectando ao broker MQTT...");
    String clientId = "ESP32-pH-" + String(random(0xffff), HEX);
    if (client.connect(clientId.c_str()))
    {
      Serial.println("conectado!");
    }
    else
    {
      Serial.print("falhou, rc=");
      Serial.print(client.state());
      Serial.println(" tentando de novo em 2s");
      delay(2000);
    }
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

  client.setServer(mqtt_server, mqtt_port);

  Serial.println("Iniciando leitura...\n");
}

float lerTensaoFiltrada()
{
  for (int i = 0; i < NUM_SAMPLES; i++)
  {
    buffer_arr[i] = analogRead(PH_PIN);
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

  float leituraMedia = (float)soma / qtd;
  return (leituraMedia * 3.3) / 4095.0;
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

  display.display();
}

void publicarMQTT(float tensao, float ph)
{
  String payload = "{\"ph\":" + String(ph, 2) + ",\"tensao\":" + String(tensao, 3) + "}";
  client.publish(topico_ph, payload.c_str());
  Serial.println("Publicado no MQTT: " + payload);
}

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
  client.loop();

  float tensao = lerTensaoFiltrada();
  float ph = PH_SLOPE * tensao + PH_OFFSET;

  Serial.print("Tensao: ");
  Serial.print(tensao, 3);
  Serial.print(" V   |   pH: ");
  Serial.println(ph, 2);

  enviarLeitura(ph, tensao);
  mostrarNoOLED(tensao, ph);
  publicarMQTT(tensao, ph);

  delay(1000);
}
