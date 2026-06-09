#include <WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>
#include <math.h>

const char* ssid = "ModoB";
const char* password = "1234567899";

#define SDA_PIN 21
#define SCL_PIN 22
#define TCA_ADDR 0x70
#define MPU_ADDR 0x68
#define REG_PWR_MGMT_1   0x6B
#define REG_WHO_AM_I     0x75
#define REG_ACCEL_XOUT_H 0x3B

const uint8_t canales[] = {2, 3, 4, 5, 6, 7};
const uint8_t numCanales = sizeof(canales) / sizeof(canales[0]);

WiFiUDP udp;
const uint16_t DISCOVERY_PORT = 4210;
const uint16_t DATA_PORT = 4211;

IPAddress laptopIP;
bool laptopEncontrada = false;
unsigned long lastHello = 0;
unsigned long lastSend = 0;

struct SensorRow {
  bool ok;
  uint8_t ch;
  float ax, ay, az;
  float gx, gy, gz;
};

IPAddress calcBroadcast(IPAddress ip, IPAddress mask) {
  IPAddress b;
  for (int i = 0; i < 4; i++) b[i] = (ip[i] & mask[i]) | (~mask[i]);
  return b;
}

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

bool read14(uint8_t addr, uint8_t reg, uint8_t* buf) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, (uint8_t)14) != 14) return false;
  for (int i = 0; i < 14; i++) {
    if (!Wire.available()) return false;
    buf[i] = Wire.read();
  }
  return true;
}

int16_t to16(uint8_t h, uint8_t l) {
  return (int16_t)((h << 8) | l);
}

bool leerCanal(uint8_t ch, SensorRow &row) {
  row.ok = false;
  row.ch = ch;

  tcaSelect(ch);
  delay(5);

  if (!existsI2C(MPU_ADDR)) return false;
  if (!writeByte(MPU_ADDR, REG_PWR_MGMT_1, 0x00)) return false;

  uint8_t raw[14];
  if (!read14(MPU_ADDR, REG_ACCEL_XOUT_H, raw)) return false;

  int16_t ax = to16(raw[0], raw[1]);
  int16_t ay = to16(raw[2], raw[3]);
  int16_t az = to16(raw[4], raw[5]);
  int16_t gx = to16(raw[8], raw[9]);
  int16_t gy = to16(raw[10], raw[11]);
  int16_t gz = to16(raw[12], raw[13]);

  row.ax = ax / 16384.0;
  row.ay = ay / 16384.0;
  row.az = az / 16384.0;
  row.gx = gx / 131.0;
  row.gy = gy / 131.0;
  row.gz = gz / 131.0;
  row.ok = true;
  return true;
}

void conectarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("IP ESP32: ");
  Serial.println(WiFi.localIP());

  udp.begin(DISCOVERY_PORT);
}

void enviarHello() {
  IPAddress bcast = calcBroadcast(WiFi.localIP(), WiFi.subnetMask());
  String msg = "HELLO_ESP32|ip=" + WiFi.localIP().toString() + "|port=" + String(DATA_PORT);

  udp.beginPacket(bcast, DISCOVERY_PORT);
  udp.print(msg);
  udp.endPacket();

  Serial.print("Broadcast: ");
  Serial.println(msg);
}

void procesarUDP() {
  int packetSize = udp.parsePacket();
  if (!packetSize) return;

  char buf[256];
  int len = udp.read(buf, sizeof(buf) - 1);
  if (len <= 0) return;
  buf[len] = '\0';

  String msg = String(buf);
  IPAddress remote = udp.remoteIP();

  if (msg.startsWith("HELLO_LAPTOP")) {
    laptopIP = remote;
    laptopEncontrada = true;
    Serial.print("Laptop encontrada: ");
    Serial.println(laptopIP);

    String ack = "ACK_ESP32|esp_ip=" + WiFi.localIP().toString() + "|laptop_ip=" + laptopIP.toString();
    udp.beginPacket(laptopIP, DISCOVERY_PORT);
    udp.print(ack);
    udp.endPacket();
  }
}

void enviarLinea(const String &linea) {
  Serial.println(linea);

  if (laptopEncontrada) {
    udp.beginPacket(laptopIP, DATA_PORT);
    udp.print(linea);
    udp.endPacket();
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  conectarWiFi();

  if (!existsI2C(TCA_ADDR)) {
    Serial.println("ERROR: no se detecta TCA9548A en 0x70");
    while (true) delay(1000);
  }

  Serial.println("TCA9548A OK");
  enviarHello();
  lastHello = millis();
}

void loop() {
  procesarUDP();

  if (!laptopEncontrada && millis() - lastHello > 3000) {
    enviarHello();
    lastHello = millis();
  }

  if (millis() - lastSend > 50) {
    for (uint8_t i = 0; i < numCanales; i++) {
      SensorRow s;
      bool ok = leerCanal(canales[i], s);

      String linea;
      if (ok) {
        linea = "CH=" + String(s.ch) +
                " AX=" + String(s.ax, 3) +
                " AY=" + String(s.ay, 3) +
                " AZ=" + String(s.az, 3) +
                " GX=" + String(s.gx, 3) +
                " GY=" + String(s.gy, 3) +
                " GZ=" + String(s.gz, 3);
      } else {
        linea = "CH=" + String(canales[i]) + " NO_DETECTADO";
      }

      enviarLinea(linea);
      delay(2);
    }
    lastSend = millis();
  }
}