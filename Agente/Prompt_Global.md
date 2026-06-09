# CONTEXTO DEL PROYECTO — MANUEL ASSIST
## Prompt de contexto para desarrollo con Claude Code

---

## 1. DESCRIPCIÓN GENERAL DEL PROYECTO

**Manuel Assist** es un guante robótico asistivo para personas con movilidad reducida que conservan movimiento funcional en una mano. El guante traduce movimientos de los dedos y señales musculares en comandos de teclado y mouse para controlar una computadora, eliminando la dependencia de periféricos convencionales.

Este es un proyecto académico de la materia **Robótica I (COM 480)** de la Universidad San Francisco Xavier de Chuquisaca (USFX), Sucre, Bolivia. El equipo está compuesto por 4 integrantes. Yo (Bryan Daniel Martínez Cabezas) soy el responsable del desarrollo de software e inteligencia artificial.

---

## 2. ARQUITECTURA DE HARDWARE

El sistema tiene los siguientes componentes físicos ya armados y funcionando:

### Sensores (en el guante):
- **5× MPU6050 (GY-521)** — Sensores IMU de 6-DoF (acelerómetro 3 ejes + giroscopio 3 ejes), uno por dedo (pulgar, índice, medio, anular, meñique)
- Conectados al multiplexor **TCA9548A** en los canales I2C: 2, 3, 4, 5, 6
- Dirección I2C del TCA9548A: 0x70
- Dirección I2C de cada MPU6050: 0x68

### Procesamiento y comunicación:
- **ESP32 WROOM-32** — Lee los sensores directamente vía I2C (Wire en pines 21/22) y transmite datos por Wi-Fi UDP
- NO hay Arduino Nano separado; el ESP32 hace ambas funciones (lectura + transmisión)

### Sensor EMG (NO conectado aún):
- **Gravity: Analog EMG Sensor (DFRobot/OYMotion)** — Para detección de tensión muscular del antebrazo
- Se integrará después. Por ahora la IA trabaja solo con los 5 MPU6050

### Alimentación:
- **Batería Li-Ion 18650** (3.7V / 2500mAh) + módulo **TP4056** con protección + boost a 5V

---

## 3. FLUJO DE DATOS ACTUAL

```
5× MPU6050 → TCA9548A (I2C) → ESP32 → Wi-Fi UDP → PC (Python)
```

### Formato de datos que envía el ESP32:
El ESP32 envía bloques de texto por UDP al puerto 5005. Cada bloque tiene este formato:

```
ESP32 hola mandando datos;ESP_IP=192.168.18.99;LAPTOP_IP=192.168.18.74
Canal 2 -> Ax:0.87 | Ay:-0.00 | Az:0.60 | Gx:-1.3 | Gy:1.2 | Gz:-0.5 | T:43.5 C
Canal 3 -> Ax:-0.15 | Ay:-0.80 | Az:-0.68 | Gx:-7.7 | Gy:-10.7 | Gz:-1.8 | T:42.2 C
Canal 4 -> Ax:0.08 | Ay:-1.00 | Az:0.03 | Gx:90.5 | Gy:-21.6 | Gz:-13.1 | T:42.6 C
Canal 5 -> Ax:-0.00 | Ay:-0.98 | Az:0.07 | Gx:-7.5 | Gy:0.9 | Gz:0.8 | T:43.5 C
Canal 6 -> Ax:0.18 | Ay:0.30 | Az:0.92 | Gx:0.8 | Gy:3.3 | Gz:-0.4 | T:41.6 C
```

### Mapeo de canales a dedos:
- Canal 2 = Pulgar
- Canal 3 = Índice
- Canal 4 = Medio
- Canal 5 = Anular
- Canal 6 = Meñique

### Valores por sensor (6 valores por MPU6050):
- **ax, ay, az** — Aceleración en g (rango ±2g, normalizado: valor / 16384.0)
- **gx, gy, gz** — Velocidad angular en °/s (rango ±250°/s, normalizado: valor / 131.0)
- **T** — Temperatura (NO se usa para clasificación, ignorar)

### Total de features para el modelo de IA:
- **30 features por frame** (5 sensores × 6 valores, sin temperatura, sin EMG)
- Se agrupan en **ventanas temporales de 15 frames** → **450 features por muestra**

---

## 4. PROTOCOLO DE COMUNICACIÓN

### Descubrimiento (broadcast):
1. ESP32 envía broadcast UDP al puerto 4210: `HOLA_SOY_ESP32;IP=x.x.x.x;PORT=5005`
2. Python responde: `HOLA_LAPTOP;LISTA=1`
3. ESP32 registra la IP de la laptop y empieza a enviar datos

### Envío de datos:
- Puerto: 5005
- Intervalo actual: 500ms (DEBE cambiarse a 33ms para ~30fps en producción)
- Formato: texto plano (ver sección 3)

---

## 5. DEFINICIÓN COMPLETA DE GESTOS (20 clases)

### Acciones directas (5 gestos):
| Gesto | Movimiento físico | Acción en PC |
|-------|-------------------|--------------|
| reposo | Mano abierta, sin movimiento | Nada (idle) |
| borrar | Índice enroscado | Backspace |
| espacio | Índice + pulgar juntos (touching) | Barra espaciadora |
| enter | Índice + medio juntos, subir | Enter |
| scroll_down | 4 dedos enroscados (índice+medio+anular+meñique) | Scroll abajo |
| scroll_up | 3 dedos enroscados (índice+medio+anular) | Scroll arriba |

### Modo numérico (activado cuando el pulgar se oculta debajo de la palma):
| Gesto | Movimiento | Acción |
|-------|-----------|--------|
| modo_numerico | Pulgar oculto | Bloquea cursor, activa números |
| num_1_2 | Índice posición 1 o 2 | Tecla 1 o 2 |
| num_3_4 | Medio posición 1 o 2 | Tecla 3 o 4 |
| num_5_6 | Anular posición 1 o 2 | Tecla 5 o 6 |
| num_7_8 | Meñique posición 1 o 2 | Tecla 7 o 8 |
| num_9 | Índice + medio juntos | Tecla 9 |
| num_0 | Índice + medio + anular + meñique juntos | Tecla 0 |

### Modo letras (4 dedos, 3 posiciones cada uno = 12 zonas):
| Gesto | Dedo + Posición | Letras |
|-------|----------------|--------|
| letra_pulgar_1 | Pulgar zona 1 | A-B |
| letra_pulgar_2 | Pulgar zona 2 | C-D |
| letra_pulgar_3 | Pulgar zona 3 | E-G |
| letra_medio_1 | Medio zona 1 | H-J |
| letra_medio_2 | Medio zona 2 | K-L |
| letra_medio_3 | Medio zona 3 | M-N |
| letra_anular_1 | Anular zona 1 | O-P |
| letra_anular_2 | Anular zona 2 | Q-R |
| letra_anular_3 | Anular zona 3 | S-T |
| letra_menique_1 | Meñique zona 1 | U-V |
| letra_menique_2 | Meñique zona 2 | W-X |
| letra_menique_3 | Meñique zona 3 | Y-Z |

### Acciones EMG (NO pasan por el MLP, son umbral fijo):
| Gesto | Condición | Acción |
|-------|----------|--------|
| click_izq | EMG > umbral durante >0.3s | Click izquierdo |
| windows | EMG > umbral durante 5s | Tecla Windows |

### Control de cursor (NO es una clase del MLP):
- El movimiento del índice (inclinación del MPU6050 del canal 3) se mapea directamente a movimiento del mouse dx/dy
- Es lectura directa del acelerómetro, no clasificación

---

## 6. ARQUITECTURA DEL MODELO DE IA

### Modelo: MLP (Perceptrón Multicapa) en PyTorch

```
Input(450) → FC(256) → BatchNorm → ReLU → Dropout(0.3)
           → FC(128) → BatchNorm → ReLU → Dropout(0.3)
           → FC(64)  → BatchNorm → ReLU → Dropout(0.2)
           → FC(N_CLASES) → Softmax
```

### Parámetros:
- **Input size:** 450 (15 frames × 30 features, SIN temperatura, SIN EMG)
- **N clases:** ~20 gestos (se definirá exacto según los gestos que se graben)
- **Ventana temporal:** 15 frames consecutivos
- **Umbral de confianza:** ≥65% para ejecutar acción
- **Filtro de histéresis:** gesto debe mantenerse estable ≥200ms antes de ejecutarse

### Entrenamiento:
- Optimizer: Adam (lr=1e-3, weight_decay=1e-4)
- Scheduler: CosineAnnealingLR
- Epochs: 60
- Batch size: 32
- Loss: CrossEntropyLoss
- Split: 70% train / 15% val / 15% test
- Normalización: StandardScaler (media 0, std 1)

### Data Augmentation:
- Ruido gaussiano basado en la desviación estándar real de cada sensor
- Objetivo: de 100 muestras reales → 1000 por gesto con DA

---

## 7. CÓDIGO ACTUAL DEL ESP32 (Firmware de Atzel)

```cpp
// RESUMEN del firmware — NO modificar sin consultar a Atzel
// - Lee 5 MPU6050 vía TCA9548A (canales 2-6)
// - Se conecta a Wi-Fi
// - Envía datos por UDP broadcast para descubrimiento
// - Cuando la laptop responde, envía datos solo a ella
// - Intervalo de envío: 500ms (cambiar a 33ms para producción)
// - Formato: texto plano con "Canal X -> Ax:val | Ay:val | ..."
```

### Lo que hay que pedirle a Atzel que cambie eventualmente:
1. `INTERVALO_ENVIO` de 500 a 33 (para ~30fps)
2. Formato binario (floats empaquetados) en vez de texto (opcional, para reducir latencia)
3. Agregar lectura del EMG cuando se conecte (pin analógico A0)

---

## 8. QUÉ NECESITO DESARROLLAR (MI PARTE — SOFTWARE + IA)

### Scripts Python necesarios:

#### A) Script de grabación de datos (`grabar_datos.py`)
- Recibe datos UDP del ESP32 en puerto 5005
- Parsea el texto y extrae los 30 valores numéricos (ax,ay,az,gx,gy,gz × 5 dedos)
- El usuario indica qué gesto está haciendo
- Graba ventanas de 15 frames con su etiqueta
- Guarda todo en CSV
- Funcionalidad de Data Augmentation integrada
- Target: 100 repeticiones reales por gesto → DA a 1000

#### B) Notebook de Colab para entrenamiento (`Manuel_Assist_Train.ipynb`)
- Ya tengo un notebook base con datos simulados (link: https://colab.research.google.com/drive/148tpdFoqfcyTEzqSkAh-D7GTLrTKy2AU?usp=sharing)
- Necesito adaptar la celda de carga de datos para leer el CSV real en vez de simular
- El resto del pipeline (normalización, modelo, entrenamiento, evaluación) se mantiene
- Exportar: modelo.pth, scaler.pkl, metadata.json

#### C) Script receptor + control de PC (`receptor_manuel_assist.py`)
- Recibe datos UDP del ESP32
- Acumula frames en buffer circular de 15
- Normaliza con el scaler exportado
- Clasifica con el modelo MLP exportado
- Ejecuta la acción con pyautogui/pynput
- Control de cursor: lectura directa del acelerómetro del índice → mouse.move(dx, dy)
- EMG (futuro): umbral fijo para click y Windows
- Filtro de histéresis (200ms) para evitar falsos positivos

### Librerías necesarias en mi PC:
```
pip install torch numpy pandas scikit-learn matplotlib seaborn pyautogui pynput
```

---

## 9. PLAN DE TRABAJO INMEDIATO

### Sesión de mañana:
1. Recibir el guante armado de mi compañero
2. Correr el script receptor actual de Atzel para verificar que llegan datos
3. Grabar los primeros 5 gestos (reposo, borrar, espacio, enter, scroll_down) — 100 repeticiones cada uno
4. Aplicar Data Augmentation → 1000 por gesto
5. Entrenar MLP en Colab con esos 5 gestos
6. Probar clasificación en la PC con pyautogui

### Después:
7. Grabar los gestos restantes (scroll_up, letras, números)
8. Reentrenar con dataset completo (20 clases)
9. Integrar control de cursor (lectura directa del acelerómetro del índice)
10. Integrar EMG cuando se conecte
11. Documentar pruebas para el informe (Bloque VIII)

---

## 10. NOTAS TÉCNICAS IMPORTANTES

- El modelo corre en la **PC**, NO en el ESP32 ni en ningún microcontrolador. El ESP32 solo envía datos crudos.
- La detección de Windows (EMG 5s) y Click (EMG 0.3s) es **umbral fijo, no IA**. No pasa por el MLP.
- El control de cursor es **lectura directa del acelerómetro**, no clasificación MLP.
- Los datos del ESP32 llegan como **texto plano** que hay que parsear con regex o split.
- La temperatura (T) de los MPU6050 **NO se usa** como feature del modelo.
- Los canales del TCA9548A son 2,3,4,5,6 (NO 0,1,2,3,4) — Atzel los configuró así en el hardware.
- El ESP32 lee los sensores **directamente** (no hay Arduino Nano intermedio como dice el informe original — eso cambió durante la implementación).

---

## 11. ESTRUCTURA DEL CSV DE SALIDA ESPERADO

```csv
timestamp,pulgar_ax,pulgar_ay,pulgar_az,pulgar_gx,pulgar_gy,pulgar_gz,indice_ax,indice_ay,indice_az,indice_gx,indice_gy,indice_gz,medio_ax,medio_ay,medio_az,medio_gx,medio_gy,medio_gz,anular_ax,anular_ay,anular_az,anular_gx,anular_gy,anular_gz,menique_ax,menique_ay,menique_az,menique_gx,menique_gy,menique_gz,gesto
1717700000.123,0.87,-0.00,0.60,-1.3,1.2,-0.5,-0.15,-0.80,-0.68,-7.7,-10.7,-1.8,0.08,-1.00,0.03,90.5,-21.6,-13.1,-0.00,-0.98,0.07,-7.5,0.9,0.8,0.18,0.30,0.92,0.8,3.3,-0.4,reposo
```

- 30 columnas de datos + 1 de timestamp + 1 de gesto = 32 columnas
- Cada fila es un frame
- Las ventanas de 15 frames se arman después en el notebook de Colab

---

## 12. PARSING DE LOS DATOS UDP

Los datos llegan del ESP32 como texto. Hay que extraer los valores numéricos:

```python
# Ejemplo de parsing de una línea:
# "Canal 2 -> Ax:0.87 | Ay:-0.00 | Az:0.60 | Gx:-1.3 | Gy:1.2 | Gz:-0.5 | T:43.5 C"
# Extraer: [0.87, -0.00, 0.60, -1.3, 1.2, -0.5]  (ignorar T)

import re

def parse_canal(line):
    """Extrae los 6 valores (ax,ay,az,gx,gy,gz) de una línea de canal."""
    pattern = r'Ax:([-\d.]+)\s*\|\s*Ay:([-\d.]+)\s*\|\s*Az:([-\d.]+)\s*\|\s*Gx:([-\d.]+)\s*\|\s*Gy:([-\d.]+)\s*\|\s*Gz:([-\d.]+)'
    match = re.search(pattern, line)
    if match:
        return [float(match.group(i)) for i in range(1, 7)]
    return None

def parse_bloque(bloque):
    """Parsea un bloque completo de 5 canales y devuelve 30 floats."""
    lineas = bloque.strip().split('\n')
    frame = []
    for linea in lineas:
        if 'Canal' in linea and '->' in linea:
            valores = parse_canal(linea)
            if valores:
                frame.extend(valores)
    return frame if len(frame) == 30 else None
```

---

FIN DEL CONTEXTO. Con esta información, Claude Code puede desarrollar cualquiera de los scripts necesarios (grabación, entrenamiento, receptor) con conocimiento completo del proyecto.