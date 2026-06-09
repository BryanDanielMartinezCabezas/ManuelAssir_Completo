#include <Wire.h>
#include <math.h>

#define SDA_PIN 21
#define SCL_PIN 22

#define TCA_ADDR 0x70
#define MPU_ADDR_1 0x68
#define MPU_ADDR_2 0x69

#define REG_PWR_MGMT_1    0x6B
#define REG_SMPLRT_DIV    0x19
#define REG_CONFIG        0x1A
#define REG_GYRO_CONFIG   0x1B
#define REG_ACCEL_CONFIG  0x1C
#define REG_ACCEL_XOUT_H  0x3B

const uint8_t NUM_SENSORES = 5;

const uint8_t canales[NUM_SENSORES] = {2, 3, 4, 5, 6};

const char* dedos[NUM_SENSORES] = {
  "menique",
  "anular",
  "medio",
  "indice",
  "pulgar"
};

bool sensorOK[NUM_SENSORES];
uint8_t sensorAddr[NUM_SENSORES];

float gyroOffsetX[NUM_SENSORES];
float gyroOffsetY[NUM_SENSORES];
float gyroOffsetZ[NUM_SENSORES];

float neutralAngleX[NUM_SENSORES];
float neutralAngleY[NUM_SENSORES];

float angleX[NUM_SENSORES];
float angleY[NUM_SENSORES];

float angleXFilt[NUM_SENSORES];
float angleYFilt[NUM_SENSORES];

String estadoTemporal[NUM_SENSORES];
String estadoConfirmado[NUM_SENSORES];
String ultimoEstadoImpreso[NUM_SENSORES];

uint8_t contadorEstable[NUM_SENSORES];

int dedoActivo = -1;

unsigned long lastTime = 0;
unsigned long tiempoEstadoActivo[NUM_SENSORES];

const unsigned long AUTO_REPOSO_MS = 1500;

const float ALPHA_ANGLE = 0.28;
const float DEADZONE_GYRO = 2.0;
const float COMPLEMENTARY = 0.96;

// menique, anular y medio SOLO usan ULTRA.
// indice y pulgar conservan NORMAL / ULTRA.

float NORMAL_ON[NUM_SENSORES] = {
  999.0,   // menique desactivado
  999.0,   // anular desactivado
  999.0,   // medio desactivado
  5.0,     // indice
  15.0     // pulgar
};

float ULTRA_ON[NUM_SENSORES] = {
  12.0,    // menique
  4.0,     // anular
  12.0,    // medio
  12.0,    // indice
  25.0     // pulgar
};

float NORMAL_OFF[NUM_SENSORES] = {
  2.0,
  2.0,
  2.0,
  4.0,
  14.0
};

float ULTRA_OFF[NUM_SENSORES] = {
  8.0,
  8.0,
  8.0,
  8.0,
  35.0
};

const uint8_t FRAMES_CONFIRMACION = 2;
const uint8_t FRAMES_REPOSO_RAPIDO = 1;

void tcaSelect(uint8_t channel) {
  Wire.beginTransmission(TCA_ADDR);
  Wire.write(1 << channel);
  Wire.endTransmission();
}

bool existsI2C(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

bool writeByte(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

int16_t to16(uint8_t h, uint8_t l) {
  return (int16_t)((h << 8) | l);
}

bool read14(uint8_t addr, uint8_t* buf) {
  Wire.beginTransmission(addr);
  Wire.write(REG_ACCEL_XOUT_H);

  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, (uint8_t)14) != 14) return false;

  for (int i = 0; i < 14; i++) {
    buf[i] = Wire.read();
  }

  return true;
}

bool readMPU(uint8_t addr,
             float &ax, float &ay, float &az,
             float &gx, float &gy, float &gz) {
  uint8_t raw[14];

  if (!read14(addr, raw)) return false;

  int16_t rax = to16(raw[0], raw[1]);
  int16_t ray = to16(raw[2], raw[3]);
  int16_t raz = to16(raw[4], raw[5]);

  int16_t rgx = to16(raw[8], raw[9]);
  int16_t rgy = to16(raw[10], raw[11]);
  int16_t rgz = to16(raw[12], raw[13]);

  ax = rax / 16384.0;
  ay = ray / 16384.0;
  az = raz / 16384.0;

  gx = rgx / 131.0;
  gy = rgy / 131.0;
  gz = rgz / 131.0;

  return true;
}

bool configurarMPU(uint8_t addr) {
  if (!writeByte(addr, REG_PWR_MGMT_1, 0x00)) return false;
  delay(80);

  writeByte(addr, REG_SMPLRT_DIV, 0x07);
  writeByte(addr, REG_CONFIG, 0x03);
  writeByte(addr, REG_GYRO_CONFIG, 0x00);
  writeByte(addr, REG_ACCEL_CONFIG, 0x00);

  delay(80);
  return true;
}

float deadzone(float v) {
  if (abs(v) < DEADZONE_GYRO) return 0.0;
  return v;
}

void detectarSensores() {
  for (uint8_t i = 0; i < NUM_SENSORES; i++) {
    sensorOK[i] = false;
    sensorAddr[i] = 0;

    estadoTemporal[i] = "reposo";
    estadoConfirmado[i] = "reposo";
    ultimoEstadoImpreso[i] = "";
    contadorEstable[i] = 0;
    tiempoEstadoActivo[i] = 0;

    tcaSelect(canales[i]);
    delay(30);

    if (existsI2C(MPU_ADDR_1)) {
      sensorAddr[i] = MPU_ADDR_1;
      sensorOK[i] = configurarMPU(MPU_ADDR_1);
    }
    else if (existsI2C(MPU_ADDR_2)) {
      sensorAddr[i] = MPU_ADDR_2;
      sensorOK[i] = configurarMPU(MPU_ADDR_2);
    }
  }
}

void calibrarSensores() {
  Serial.println("calibrando mano en reposo");
  delay(3000);

  const int muestras = 700;

  for (uint8_t i = 0; i < NUM_SENSORES; i++) {
    gyroOffsetX[i] = 0;
    gyroOffsetY[i] = 0;
    gyroOffsetZ[i] = 0;

    neutralAngleX[i] = 0;
    neutralAngleY[i] = 0;

    angleX[i] = 0;
    angleY[i] = 0;
    angleXFilt[i] = 0;
    angleYFilt[i] = 0;

    if (!sensorOK[i]) continue;

    float sumGX = 0;
    float sumGY = 0;
    float sumGZ = 0;

    float sumAXang = 0;
    float sumAYang = 0;

    int validas = 0;

    for (int m = 0; m < muestras; m++) {
      tcaSelect(canales[i]);
      delay(2);

      float ax, ay, az, gx, gy, gz;

      if (readMPU(sensorAddr[i], ax, ay, az, gx, gy, gz)) {
        float accelAngleX = atan2(ay, az) * 180.0 / PI;
        float accelAngleY = atan2(-ax, sqrt((ay * ay) + (az * az))) * 180.0 / PI;

        sumGX += gx;
        sumGY += gy;
        sumGZ += gz;

        sumAXang += accelAngleX;
        sumAYang += accelAngleY;

        validas++;
      }

      delay(3);
    }

    if (validas > 0) {
      gyroOffsetX[i] = sumGX / validas;
      gyroOffsetY[i] = sumGY / validas;
      gyroOffsetZ[i] = sumGZ / validas;

      neutralAngleX[i] = sumAXang / validas;
      neutralAngleY[i] = sumAYang / validas;
    }
  }

  Serial.println("calibracion ok");
}

String clasificarMovimiento(uint8_t i) {
  float intensidad = sqrt(
    angleXFilt[i] * angleXFilt[i] +
    angleYFilt[i] * angleYFilt[i]
  );

  if (intensidad < NORMAL_OFF[i]) {
    return "reposo";
  }

  if (estadoConfirmado[i] == "ultra" && intensidad > ULTRA_OFF[i]) {
    return "ultra";
  }

  if (intensidad >= ULTRA_ON[i]) {
    return "ultra";
  }

  // Solo indice y pulgar pueden entrar en NORMAL
  if ((i == 3 || i == 4) && intensidad >= NORMAL_ON[i]) {
    return "normal";
  }

  return estadoConfirmado[i];
}

void confirmarEstado(uint8_t i, String nuevoEstado) {
  String estadoAnterior = estadoConfirmado[i];

  if (nuevoEstado == "reposo") {
    if (estadoTemporal[i] == "reposo") {
      contadorEstable[i]++;
    } else {
      estadoTemporal[i] = "reposo";
      contadorEstable[i] = 0;
    }

    if (contadorEstable[i] >= FRAMES_REPOSO_RAPIDO) {
      estadoConfirmado[i] = "reposo";
      tiempoEstadoActivo[i] = 0;
    }

    return;
  }

  if (nuevoEstado == estadoTemporal[i]) {
    contadorEstable[i]++;
  } else {
    estadoTemporal[i] = nuevoEstado;
    contadorEstable[i] = 0;
  }

  if (contadorEstable[i] >= FRAMES_CONFIRMACION) {
    estadoConfirmado[i] = nuevoEstado;

    // Solo menique, anular y medio usan autoreposo.
    // Indice y pulgar conservan su estado hasta volver físicamente a reposo.
    if (i != 3 && i != 4 && estadoAnterior == "reposo") {
      tiempoEstadoActivo[i] = millis();
    }
  }
}

void aplicarAutoReposoSoloTresDedos() {
  for (uint8_t i = 0; i < NUM_SENSORES; i++) {
    // 0 menique, 1 anular, 2 medio tienen autoreposo.
    // 3 indice y 4 pulgar NO tienen autoreposo.
    if (i == 3 || i == 4) continue;

    if (estadoConfirmado[i] == "ultra") {
      if (tiempoEstadoActivo[i] > 0 && millis() - tiempoEstadoActivo[i] >= AUTO_REPOSO_MS) {
        estadoTemporal[i] = "reposo";
        estadoConfirmado[i] = "reposo";
        contadorEstable[i] = 0;
        tiempoEstadoActivo[i] = 0;

        angleX[i] = 0;
        angleY[i] = 0;
        angleXFilt[i] = 0;
        angleYFilt[i] = 0;

        if (dedoActivo == i) {
          dedoActivo = -1;
        }
      }
    }
  }
}

void resetearDedosBloqueados(int activo) {
  for (uint8_t i = 0; i < NUM_SENSORES; i++) {
    if ((int)i == activo) continue;

    estadoTemporal[i] = "reposo";
    estadoConfirmado[i] = "reposo";
    contadorEstable[i] = 0;
    tiempoEstadoActivo[i] = 0;

    angleX[i] = 0;
    angleY[i] = 0;
    angleXFilt[i] = 0;
    angleYFilt[i] = 0;
  }
}

void actualizarDedo(uint8_t i, float dt) {
  if (!sensorOK[i]) return;

  tcaSelect(canales[i]);
  delay(2);

  float ax, ay, az, gx, gy, gz;

  if (!readMPU(sensorAddr[i], ax, ay, az, gx, gy, gz)) {
    return;
  }

  gx = deadzone(gx - gyroOffsetX[i]);
  gy = deadzone(gy - gyroOffsetY[i]);

  float accelAngleX = atan2(ay, az) * 180.0 / PI;
  float accelAngleY = atan2(-ax, sqrt((ay * ay) + (az * az))) * 180.0 / PI;

  accelAngleX -= neutralAngleX[i];
  accelAngleY -= neutralAngleY[i];

  angleX[i] = COMPLEMENTARY * (angleX[i] + gx * dt) + (1.0 - COMPLEMENTARY) * accelAngleX;
  angleY[i] = COMPLEMENTARY * (angleY[i] + gy * dt) + (1.0 - COMPLEMENTARY) * accelAngleY;

  angleXFilt[i] = (ALPHA_ANGLE * angleX[i]) + ((1.0 - ALPHA_ANGLE) * angleXFilt[i]);
  angleYFilt[i] = (ALPHA_ANGLE * angleY[i]) + ((1.0 - ALPHA_ANGLE) * angleYFilt[i]);

  String nuevoEstado = clasificarMovimiento(i);
  confirmarEstado(i, nuevoEstado);
}

void actualizarDedoActivo(float dt) {
  if (dedoActivo < 0) return;

  actualizarDedo(dedoActivo, dt);

  if (estadoConfirmado[dedoActivo] == "reposo") {
    dedoActivo = -1;
  }
}

void buscarNuevoDedoActivo(float dt) {
  for (uint8_t i = 0; i < NUM_SENSORES; i++) {
    actualizarDedo(i, dt);

    if (estadoConfirmado[i] != "reposo") {
      dedoActivo = i;
      resetearDedosBloqueados(dedoActivo);
      break;
    }
  }
}

void imprimirCambios() {
  bool huboCambio = false;

  for (uint8_t i = 0; i < NUM_SENSORES; i++) {
    if (estadoConfirmado[i] != ultimoEstadoImpreso[i]) {
      huboCambio = true;
      break;
    }
  }

  if (!huboCambio) return;

  for (uint8_t i = 0; i < NUM_SENSORES; i++) {
    Serial.print(dedos[i]);
    Serial.print(" : ");
    Serial.println(estadoConfirmado[i]);

    ultimoEstadoImpreso[i] = estadoConfirmado[i];
  }

  Serial.println("--------------------");
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  detectarSensores();
  calibrarSensores();

  for (uint8_t i = 0; i < NUM_SENSORES; i++) {
    ultimoEstadoImpreso[i] = "";
  }

  lastTime = millis();
}

void loop() {
  unsigned long now = millis();
  float dt = (now - lastTime) / 1000.0;
  lastTime = now;

  if (dt <= 0 || dt > 0.15) {
    dt = 0.02;
  }

  if (dedoActivo >= 0) {
    actualizarDedoActivo(dt);
  } else {
    buscarNuevoDedoActivo(dt);
  }

  aplicarAutoReposoSoloTresDedos();

  imprimirCambios();

  delay(15);
}
