/*
  Manuel Assist — Firmware V02 (Serial puro, sin WiFi)
  Hardware: 5x MPU6050 → TCA9548A (canales 2-6) → ESP32 WROOM-32
  Baud: 115200
  Formato de salida por línea:
    CH=2 AX=0.000 AY=0.000 AZ=0.000 GX=0.000 GY=0.000 GZ=0.000
  Un bloque completo = 5 líneas (canales 2,3,4,5,6)
*/

#include <Wire.h>

#define SDA_PIN  21
#define SCL_PIN  22
#define TCA_ADDR 0x70
#define MPU_ADDR 0x68

#define REG_PWR_MGMT_1   0x6B
#define REG_ACCEL_XOUT_H 0x3B

// Canales TCA9548A → dedos: 2=Pulgar 3=Índice 4=Medio 5=Anular 6=Meñique
const uint8_t CANALES[]   = {2, 3, 4, 5, 6};
const uint8_t N_CANALES   = 5;

// ── Intervalo entre bloques (ms) ─────────────────────────────────────
// 50ms ≈ 20 fps  |  reduce a 33ms para ~30fps si el hardware aguanta
const uint16_t INTERVALO_ENVIO = 50;

// ── Utilidades I2C ────────────────────────────────────────────────────
void tcaSelect(uint8_t ch) {
  Wire.beginTransmission(TCA_ADDR);
  Wire.write(1 << ch);
  Wire.endTransmission();
}

bool writeByte(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool read14(uint8_t addr, uint8_t reg, uint8_t* buf) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, (uint8_t)14) != 14) return false;
  for (int i = 0; i < 14; i++) buf[i] = Wire.read();
  return true;
}

bool existsI2C(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

int16_t to16(uint8_t h, uint8_t l) {
  return (int16_t)((h << 8) | l);
}

// ── Leer un canal ─────────────────────────────────────────────────────
bool leerCanal(uint8_t ch,
               float &ax, float &ay, float &az,
               float &gx, float &gy, float &gz) {
  tcaSelect(ch);
  delayMicroseconds(200);

  if (!existsI2C(MPU_ADDR)) return false;
  writeByte(MPU_ADDR, REG_PWR_MGMT_1, 0x00);  // wake up

  uint8_t raw[14];
  if (!read14(MPU_ADDR, REG_ACCEL_XOUT_H, raw)) return false;

  ax = to16(raw[0],  raw[1])  / 16384.0f;
  ay = to16(raw[2],  raw[3])  / 16384.0f;
  az = to16(raw[4],  raw[5])  / 16384.0f;
  // raw[6..7] = temperatura — ignorada
  gx = to16(raw[8],  raw[9])  / 131.0f;
  gy = to16(raw[10], raw[11]) / 131.0f;
  gz = to16(raw[12], raw[13]) / 131.0f;
  return true;
}

// ── Setup ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);  // 400kHz para mayor velocidad

  if (!existsI2C(TCA_ADDR)) {
    Serial.println("ERROR: TCA9548A no detectado en 0x70");
    while (true) delay(1000);
  }

  Serial.println("Manuel Assist V02 listo");
}

// ── Loop ──────────────────────────────────────────────────────────────
unsigned long lastSend = 0;

void loop() {
  if (millis() - lastSend < INTERVALO_ENVIO) return;
  lastSend = millis();

  for (uint8_t i = 0; i < N_CANALES; i++) {
    uint8_t ch = CANALES[i];
    float ax, ay, az, gx, gy, gz;

    if (leerCanal(ch, ax, ay, az, gx, gy, gz)) {
      Serial.print("CH="); Serial.print(ch);
      Serial.print(" AX="); Serial.print(ax, 3);
      Serial.print(" AY="); Serial.print(ay, 3);
      Serial.print(" AZ="); Serial.print(az, 3);
      Serial.print(" GX="); Serial.print(gx, 3);
      Serial.print(" GY="); Serial.print(gy, 3);
      Serial.print(" GZ="); Serial.println(gz, 3);
    } else {
      Serial.print("CH="); Serial.print(ch);
      Serial.println(" NO_DETECTADO");
    }
  }
}
