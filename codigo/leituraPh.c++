  
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

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

// ===== Calibração do pH =====
// pH = PH_SLOPE * tensao + PH_OFFSET
float PH_SLOPE  = -5.70;
float PH_OFFSET = 21.34;

int buffer_arr[NUM_SAMPLES];

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
  display.println("Monitor de pH");
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

void loop()
{
  float tensao = lerTensaoFiltrada();
  float ph = PH_SLOPE * tensao + PH_OFFSET;

  Serial.print("Tensao: ");
  Serial.print(tensao, 3);
  Serial.print(" V   |   pH: ");
  Serial.println(ph, 2);

  mostrarNoOLED(tensao, ph);

  delay(1000);
}