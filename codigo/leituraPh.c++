#include <Arduino.h>

#define PH_PIN 35
#define NUM_SAMPLES 15

// ===== Parâmetros de calibração (AJUSTE conforme sua calibração) =====
// pH = PH_SLOPE * tensao + PH_OFFSET
//
// Para calibrar corretamente:
// 1. Mergulhe o sensor em solução tampão pH 7.0, anote a tensão média (V7)
// 2. Mergulhe o sensor em solução tampão pH 4.0, anote a tensão média (V4)
// 3. PH_SLOPE  = (4.0 - 7.0) / (V4 - V7)
// 4. PH_OFFSET = 7.0 - PH_SLOPE * V7
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

  analogReadResolution(12);                    // ADC de 12 bits: 0 a 4095
  analogSetPinAttenuation(PH_PIN, ADC_11db);    // Faixa de leitura ~0-3.3V

  Serial.println("Iniciando leitura...\n");
}

float lerTensaoFiltrada()
{
  // Coleta várias amostras
  for (int i = 0; i < NUM_SAMPLES; i++)
  {
    buffer_arr[i] = analogRead(PH_PIN);
    delay(20);
  }

  // Ordena (bubble sort simples)
  for (int i = 0; i < NUM_SAMPLES - 1; i++)
    for (int j = i + 1; j < NUM_SAMPLES; j++)
      if (buffer_arr[i] > buffer_arr[j])
      {
        int temp      = buffer_arr[i];
        buffer_arr[i] = buffer_arr[j];
        buffer_arr[j] = temp;
      }

  // Descarta os extremos e tira a média da parte central
  long soma = 0;
  int inicio = NUM_SAMPLES / 4;
  int fim    = NUM_SAMPLES - inicio;
  int qtd    = fim - inicio;

  for (int i = inicio; i < fim; i++)
    soma += buffer_arr[i];

  float leituraMedia = (float)soma / qtd;

  return (leituraMedia * 3.3) / 4095.0;
}

void loop()
{
  float tensao = lerTensaoFiltrada();
  float ph = PH_SLOPE * tensao + PH_OFFSET;

  Serial.print("Tensao: ");
  Serial.print(tensao, 3);
  Serial.print(" V   |   pH: ");
  Serial.println(ph, 2);

  delay(1000);
}