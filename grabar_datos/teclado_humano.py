"""
Manuel Assist — Teclado Humano
Uso: python teclado_humano.py

Mapeo de letras por dedo (conteo de activaciones):
  Pulgar : a b c d e f        (x1 x2 x3 x4 x5 x6)
  Indice : g h i j k l        (x1 x2 x3 x4 x5 x6)
  Medio  : m n ñ o p          (x1 x2 x3 x4 x5)
  Anular : q r s t u          (x1 x2 x3 x4 x5)
  Menique: v w x y z          (x1 x2 x3 x4 x5)

Confirmación:
  - 2 segundos en reposo      → escribe la letra pendiente
  - Cambiar a otro dedo       → confirma la anterior, empieza la nueva

Controles (función, no escriben texto):
  [F5]   activar teclado
  [F6]   pausar teclado
  Ctrl+C salir
"""

import re
import time
import threading
import serial
from pynput.keyboard import Controller, Key, Listener as KbListener

# ── Config ────────────────────────────────────────────────────────────
SERIAL_PORT   = "COM4"
BAUD_RATE     = 115200
CONFIRM_DELAY = 2.0   # segundos en reposo para confirmar letra

# ── Mapeo letras ──────────────────────────────────────────────────────
LETTER_MAP = {
    "pulgar":  ['a', 'b', 'c', 'd', 'e', 'f'],
    "indice":  ['g', 'h', 'i', 'j', 'k', 'l'],
    "medio":   ['m', 'n', 'ñ', 'o', 'p'],
    "anular":  ['q', 'r', 's', 't', 'u'],
    "menique": ['v', 'w', 'x', 'y', 'z'],
}

DEDOS_ORDEN = ["menique", "anular", "medio", "indice", "pulgar"]

# ── Teclado ───────────────────────────────────────────────────────────
kb = Controller()

def escribir(letra):
    kb.type(letra)

# ── Estado del sistema ────────────────────────────────────────────────
pending_finger   = None   # dedo con letra pendiente
pending_count    = 0      # cuántas veces se activó ese dedo
all_reposo_since = None   # timestamp cuando todos volvieron a reposo
prev_states      = {d: "reposo" for d in DEDOS_ORDEN}
control_activo   = False
_lock            = threading.Lock()

def letra_pendiente():
    if pending_finger is None or pending_count == 0:
        return None
    letras = LETTER_MAP.get(pending_finger, [])
    if not letras:
        return None
    idx = (pending_count - 1) % len(letras)
    return letras[idx]

def confirmar():
    global pending_finger, pending_count, all_reposo_since
    letra = letra_pendiente()
    if letra:
        escribir(letra)
        print(f"\n  ✓  '{letra}'  ({pending_finger} ×{pending_count})\n")
    pending_finger   = None
    pending_count    = 0
    all_reposo_since = None

# ── Parser ────────────────────────────────────────────────────────────
_LINE_RE = re.compile(r"^(\w+)\s*:\s*(\w+)$")

def parse_block(lines):
    estado = {}
    for line in lines:
        m = _LINE_RE.match(line.strip())
        if m:
            estado[m.group(1)] = m.group(2)
    return estado

def procesar_bloque(estado):
    global pending_finger, pending_count, all_reposo_since, prev_states

    if not control_activo:
        prev_states = dict(estado)
        return

    now = time.time()

    # Detectar rising edge: qué dedo pasó de reposo → activo
    rising = None
    for dedo in DEDOS_ORDEN:
        prev = prev_states.get(dedo, "reposo")
        curr = estado.get(dedo, "reposo")
        if prev == "reposo" and curr == "activo":
            rising = dedo
            break

    prev_states = dict(estado)

    todos_reposo = all(
        estado.get(d, "reposo") == "reposo" for d in DEDOS_ORDEN
    )

    if rising:
        # Hay activación nueva — resetear timer de reposo
        all_reposo_since = None

        if rising == pending_finger:
            # Mismo dedo: avanzar a la siguiente letra
            pending_count += 1
        else:
            # Dedo diferente: confirmar letra anterior y empezar nueva
            if pending_finger is not None:
                confirmar()
            pending_finger = rising
            pending_count  = 1

        letra = letra_pendiente()
        letras = LETTER_MAP.get(pending_finger, [])
        print(
            f"\r  {pending_finger} ×{pending_count} → '{letra}'  "
            f"[{'  '.join(letras)}]  (2s reposo para confirmar)    ",
            end="", flush=True
        )

    elif todos_reposo and pending_finger is not None:
        # Todos en reposo con letra pendiente → arrancar/revisar timer
        if all_reposo_since is None:
            all_reposo_since = now
        elif now - all_reposo_since >= CONFIRM_DELAY:
            confirmar()

    elif not todos_reposo:
        # Algún dedo sigue activo — resetear timer
        all_reposo_since = None

# ── Serial ────────────────────────────────────────────────────────────
def abrir_serial():
    try:
        s = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print(f"✓ ESP32 en {SERIAL_PORT}\n")
        return s
    except serial.SerialException:
        print("✗ ESP32 no encontrado en COM4.")
        raise SystemExit(1)

# ── Control pausa/resume ──────────────────────────────────────────────
def on_key_press(key):
    global control_activo
    try:
        if key == Key.f5:
            control_activo = True
            print("\n  ▶ Teclado ACTIVO\n")
            _imprimir_mapa()
        elif key == Key.f6:
            control_activo = False
            print("\n  ⏸ Teclado PAUSADO — presiona [F5] para reanudar\n")
    except Exception:
        pass

def _imprimir_mapa():
    print("  ┌─────────────────────────────────────────────┐")
    for dedo, letras in LETTER_MAP.items():
        fila = "  ".join(f"×{i+1}={l}" for i, l in enumerate(letras))
        print(f"  │  {dedo:<8} {fila}")
    print("  └─────────────────────────────────────────────┘\n")

KbListener(on_press=on_key_press).start()

# ── Loop principal ────────────────────────────────────────────────────
ser = abrir_serial()

print("  Mapeo de letras:")
_imprimir_mapa()
print("  [F5] activar  |  [F6] pausar  |  Ctrl+C salir")
print("  ⏸ Abre el Bloc de Notas, haz clic en el, luego presiona [F5]...\n")

current_lines = []

try:
    while True:
        try:
            raw = ser.readline()
        except serial.SerialException:
            print("\n⚠ Serial perdido — reconectando...")
            time.sleep(1)
            ser = abrir_serial()
            continue

        if not raw:
            continue

        line = raw.decode(errors="ignore").strip()
        if not line:
            continue

        if line.startswith("---"):
            if current_lines:
                estado = parse_block(current_lines)
                with _lock:
                    procesar_bloque(estado)
            current_lines = []
        else:
            current_lines.append(line)

except KeyboardInterrupt:
    ser.close()
    print("\n\nSaliendo...")
