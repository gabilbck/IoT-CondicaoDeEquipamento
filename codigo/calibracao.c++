const int PH_PIN = 35;

void setup() {
  Serial.begin(115200);

  analogReadResolution(12);
  analogSetPinAttenuation(PH_PIN, ADC_11db);

  delay(1000);
}

void loop() {

  int adc = analogRead(PH_PIN);
  int mV = analogReadMilliVolts(PH_PIN);

  Serial.print("ADC = ");
  Serial.print(adc);

  Serial.print(" | ");
  Serial.print(mV);
  Serial.println(" mV");

  delay(200);
}