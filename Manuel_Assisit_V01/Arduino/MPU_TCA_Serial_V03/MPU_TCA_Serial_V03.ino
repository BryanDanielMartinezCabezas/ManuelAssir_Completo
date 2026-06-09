/*
  Manuel Assist — Firmware V03
  Hardware : 5× MPU6050 → TCA9548A (canales 2-6) → ESP32 WROOM-32
  Baud     : 115200
  Mejoras  :
    · Rango ±4g / ±500°/s  → no satura en gestos bruscos
    · DLPF 44 Hz            → elimina vibraciones y ruido eléctrico
    · Calibración automática al encender (giróscopo)
    · Filtro EMA por canal  → salida suavizada y estable
    · Validación de frame   → descarta lecturas corruptas

  Formato de salida (una línea por dedo, 5 líneas por trama):
    CH=2 AX=0.000 AY=0.000 AZ=0.000 GX=0.000 GY=0.000 GZ=0.000
  Mensajes de control:
    CALIBRANDO...   (al inicio)
    CALIBRADO       (cuando los datos ya son fiables)
    CH=X NO_DETECTADO
*/

#include <Wire.h>

// ── Pines ────────────────────────────────────────────────────────────
#define SDA_PIN  21
#define SCL_PIN  22

// ── Direcciones I2C ──────────────────────────────────────────────────
#define TCA_ADDR 0x70
#define MPU_ADDR 0x68

// ── Registros MPU6050 ────────────────────────────────────────────────
#define REG_PWR_MGMT_1   0x6B
#define REG_CONFIG       0x1A   // DLPF
#define REG_GYRO_CONFIG  0x1B
#define REG_ACCEL_CONFIG 0x1C
#define REG_ACCEL_XOUT_H 0x3B

// ── Configuración de rango ────────────────────────────────────────────
//  Acelerómetro ±4g  → AFS_SEL=1 → 0x08 → divisor 8192.0
//  Giróscopo ±500°/s → FS_SEL=1  → 0x08 → divisor 65.5
#define ACCEL_CFG    0x08
#define GYRO_CFG     0x08
#define ACCEL_SCALE  8192.0f
#define GYRO_SCALE   65.5f

// ── DLPF ─────────────────────────────────────────────────────────────
//  CFG=3 → ancho de banda 44 Hz (elimina vibraciones > 44 Hz)
#define DLPF_CFG     0x03

// ── Canales TCA → dedos ──────────────────────────────────────────────
//  2=Pulgar  3=Índice  4=Medio  5=Anular  6=Meñique
const uint8_t CANALES[]  = {2, 3, 4, 5, 6};
const uint8_t N_CANALES  = 5;

// ── Timing ───────────────────────────────────────────────────────────
const uint16_t INTERVALO_MS  = 50;    // ~20 fps — bajar a 33 para ~30 fps
const uint16_t CAL_MUESTRAS  = 200;  // muestras para calibración

// ── Filtro EMA ────────────────────────────────────────────────────────
//  α alto → responde rápido, α bajo → más suave
//  0.65 ≈ 80 ms de retardo a 20 fps — buen balance para gestos
const float EMA_ALPHA = 0.65f;

// ── Límites de validación (post-escala) ──────────────────────────────
const float LIM_ACCEL = 3.9f;     // g   (±4g rango, dejamos margen)
const float LIM_GYRO  = 490.0f;   // °/s (±500 rango, margen)

// ── Estado interno ───────────────────────────────────────────────────
float ema[5][6];           // [dedo][ax ay az gx gy gz]
float bias_g[5][3];        // [dedo][gx gy gz] — bias de giróscopo en reposo
bool  inicializado[5];     // canal ya tiene EMA inicial

// ── Utilidades I2C ────────────────────────────────────────────────────
void tcaSelect(uint8_t ch) {
  Wire.beginTransmission(TCA_ADDR);
  Wire.write(1 << ch);
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

bool read14(uint8_t addr, uint8_t reg, uint8_t* buf) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, (uint8_t)14) != 14) return false;
  for (int i = 0; i < 14; i++) buf[i] = Wire.read();
  return true;
}

int16_t to16(uint8_t h, uint8_t l) {
  return (int16_t)((h << 8) | l);
}

// ── Inicializar MPU6050 en un canal ──────────────────────────────────
bool initMPU(uint8_t ch) {
  tcaSelect(ch);
  delayMicroseconds(300);
  if (!existsI2C(MPU_ADDR)) return false;

  writeByte(MPU_ADDR, REG_PWR_MGMT_1,   0x00);  // wake up
  delayMicroseconds(500);
  writeByte(MPU_ADDR, REG_CONFIG,        DLPF_CFG);   // DLPF 44 Hz
  writeByte(MPU_ADDR, REG_GYRO_CONFIG,   GYRO_CFG);   // ±500°/s
  writeByte(MPU_ADDR, REG_ACCEL_CONFIG,  ACCEL_CFG);  // ±4g
  return true;
}

// ── Leer un canal (sin filtrar) ──────────────────────────────────────
bool leerRaw(uint8_t ch,
             float &ax, float &ay, float &az,
             float &gx, float &gy, float &gz) {
  tcaSelect(ch);
  delayMicroseconds(200);
  if (!existsI2C(MPU_ADDR)) return false;

  uint8_t raw[14];
  if (!read14(MPU_ADDR, REG_ACCEL_XOUT_H, raw)) return false;

  ax = to16(raw[0],  raw[1])  / ACCEL_SCALE;
  ay = to16(raw[2],  raw[3])  / ACCEL_SCALE;
  az = to16(raw[4],  raw[5])  / ACCEL_SCALE;
  // raw[6-7] = temperatura — ignorada
  gx = to16(raw[8],  raw[9])  / GYRO_SCALE;
  gy = to16(raw[10], raw[11]) / GYRO_SCALE;
  gz = to16(raw[12], raw[13]) / GYRO_SCALE;
  return true;
}

// ── Validar que el valor está dentro del rango esperado ──────────────
bool validar(float ax, float ay, float az,
             float gx, float gy, float gz) {
  if (abs(ax) > LIM_ACCEL || abs(ay) > LIM_ACCEL || abs(az) > LIM_ACCEL) return false;
  if (abs(gx) > LIM_GYRO  || abs(gy) > LIM_GYRO  || abs(gz) > LIM_GYRO)  return false;
  return true;
}

// ── Calibración de giróscopo ─────────────────────────────────────────
//  Mide bias en reposo; después se resta en cada lectura.
//  La mano debe estar QUIETA durante ~10 segundos al encender.
void calibrar() {
  Serial.println("CALIBRANDO...");
  Serial.println("  Manten el guante quieto sobre la mesa (~10s)");

  float suma[5][3] = {};   // [dedo][gx gy gz]
  int   conta[5]   = {};

  for (int m = 0; m < CAL_MUESTRAS; m++) {
    for (int i = 0; i < N_CANALES; i++) {
      float ax, ay, az, gx, gy, gz;
      if (leerRaw(CANALES[i], ax, ay, az, gx, gy, gz)) {
        if (validar(ax, ay, az, gx, gy, gz)) {
          suma[i][0] += gx;
          suma[i][1] += gy;
          suma[i][2] += gz;
          conta[i]++;
        }
      }
    }
    delay(5);  // ~5ms por muestra → 200×5 = ~1s total
  }

  for (int i = 0; i < N_CANALES; i++) {
    if (conta[i] > 10) {
      bias_g[i][0] = suma[i][0] / conta[i];
      bias_g[i][1] = suma[i][1] / conta[i];
      bias_g[i][2] = suma[i][2] / conta[i];
    } else {
      bias_g[i][0] = bias_g[i][1] = bias_g[i][2] = 0.0f;
      Serial.print("  ⚠ Canal ");
      Serial.print(CANALES[i]);
      Serial.println(" sin lecturas suficientes — bias=0");
    }
  }

  Serial.println("CALIBRADO");
}

// ── Setup ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);  // 400 kHz

  // Verificar TCA9548A
  if (!existsI2C(TCA_ADDR)) {
    Serial.println("ERROR: TCA9548A no detectado en 0x70");
    while (true) delay(1000);
  }

  // Inicializar todos los MPU6050
  Serial.println("Inicializando sensores...");
  for (int i = 0; i < N_CANALES; i++) {
    if (initMPU(CANALES[i])) {
      Serial.print("  CH="); Serial.print(CANALES[i]); Serial.println(" OK");
    } else {
      Serial.print("  CH="); Serial.print(CANALES[i]); Serial.println(" NO_DETECTADO");
    }
  }

  // Calibración
  calibrar();

  // Precalentar EMA con primeras lecturas reales
  for (int i = 0; i < N_CANALES; i++) {
    float ax, ay, az, gx, gy, gz;
    inicializado[i] = false;
    if (leerRaw(CANALES[i], ax, ay, az, gx, gy, gz)) {
      gx -= bias_g[i][0];
      gy -= bias_g[i][1];
      gz -= bias_g[i][2];
      ema[i][0] = ax; ema[i][1] = ay; ema[i][2] = az;
      ema[i][3] = gx; ema[i][4] = gy; ema[i][5] = gz;
      inicializado[i] = true;
    }
  }

  Serial.println("Manuel Assist V03 listo");
}

// ── Loop ──────────────────────────────────────────────────────────────
unsigned long lastSend = 0;

void loop() {
  if (millis() - lastSend < INTERVALO_MS) return;
  lastSend = millis();

  for (int i = 0; i < N_CANALES; i++) {
    uint8_t ch = CANALES[i];
    float ax, ay, az, gx, gy, gz;

    if (!leerRaw(ch, ax, ay, az, gx, gy, gz)) {
      Serial.print("CH="); Serial.print(ch);
      Serial.println(" NO_DETECTADO");
      continue;
    }

    // 1. Restar bias de giróscopo
    gx -= bias_g[i][0];
    gy -= bias_g[i][1];
    gz -= bias_g[i][2];

    // 2. Validar rango — si está fuera de límites, descartar
    if (!validar(ax, ay, az, gx, gy, gz)) {
      // Reenviar último valor filtrado válido en lugar de dato corrupto
      if (inicializado[i]) {
        Serial.print("CH="); Serial.print(ch);
        Serial.print(" AX="); Serial.print(ema[i][0], 3);
        Serial.print(" AY="); Serial.print(ema[i][1], 3);
        Serial.print(" AZ="); Serial.print(ema[i][2], 3);
        Serial.print(" GX="); Serial.print(ema[i][3], 3);
        Serial.print(" GY="); Serial.print(ema[i][4], 3);
        Serial.print(" GZ="); Serial.println(ema[i][5], 3);
      }
      continue;
    }

    // 3. Aplicar filtro EMA
    if (!inicializado[i]) {
      ema[i][0]=ax; ema[i][1]=ay; ema[i][2]=az;
      ema[i][3]=gx; ema[i][4]=gy; ema[i][5]=gz;
      inicializado[i] = true;
    } else {
      ema[i][0] = EMA_ALPHA*ax + (1-EMA_ALPHA)*ema[i][0];
      ema[i][1] = EMA_ALPHA*ay + (1-EMA_ALPHA)*ema[i][1];
      ema[i][2] = EMA_ALPHA*az + (1-EMA_ALPHA)*ema[i][2];
      ema[i][3] = EMA_ALPHA*gx + (1-EMA_ALPHA)*ema[i][3];
      ema[i][4] = EMA_ALPHA*gy + (1-EMA_ALPHA)*ema[i][4];
      ema[i][5] = EMA_ALPHA*gz + (1-EMA_ALPHA)*ema[i][5];
    }

    // 4. Enviar por Serial
    Serial.print("CH="); Serial.print(ch);
    Serial.print(" AX="); Serial.print(ema[i][0], 3);
    Serial.print(" AY="); Serial.print(ema[i][1], 3);
    Serial.print(" AZ="); Serial.print(ema[i][2], 3);
    Serial.print(" GX="); Serial.print(ema[i][3], 3);
    Serial.print(" GY="); Serial.print(ema[i][4], 3);
    Serial.print(" GZ="); Serial.println(ema[i][5], 3);
  }
}
