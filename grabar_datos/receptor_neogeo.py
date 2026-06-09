"""
Manuel Assist — Receptor Neo Geo (rule-based, sin ML)
Uso: python receptor_neogeo.py

Firmware esperado: bloques separados por "--------------------"
  menique : reposo
  anular  : normal
  medio   : reposo
  indice  : ultra
  pulgar  : normal
  --------------------

Controles:
  [I]     activar control
  [O]     pausar control
  Ctrl+C  salir
"""

import re
import time
import threading
import serial
from pynput.keyboard import Controller, Key, KeyCode, Listener as KbListener

# ── Config serial ─────────────────────────────────────────────────────
SERIAL_PORT  = "COM4"
BAUD_RATE    = 115200
TAP_DURATION = 0.08
TAP_COOLDOWN = 0.30

# ── Mapeo dedo + estado → gesto ───────────────────────────────────────
FINGER_GESTURE = {
    "pulgar":  {"normal": "izquierda", "ultra": "derecha"},
    "indice":  {"normal": "abajo",     "ultra": "arriba"},
    "medio":   {"normal": "btn_A",     "ultra": "btn_A"},
    "anular":  {"normal": "btn_B",     "ultra": "btn_B"},
    "menique": {"normal": "btn_C",     "ultra": "btn_C"},
}

# ── Mapeo gesto → tecla NeoRageX ──────────────────────────────────────
KEY_MAP = {
    "derecha":   Key.right,
    "izquierda": Key.left,
    "arriba":    Key.up,
    "abajo":     Key.down,
    "btn_A":     KeyCode.from_char('z'),
    "btn_B":     KeyCode.from_char('x'),
    "btn_C":     KeyCode.from_char('a'),
    "btn_D":     KeyCode.from_char('s'),
    "start":     Key.enter,
}

HOLD_GESTURES = {"derecha", "izquierda", "arriba", "abajo"}
TAP_GESTURES  = {"btn_A", "btn_B", "btn_C", "btn_D", "start"}

EMOJIS = {
    "derecha":   "➡ ", "izquierda": "⬅ ",
    "arriba":    "⬆ ", "abajo":     "⬇ ",
    "btn_A":     "☝ ", "btn_B":     "✌ ",
    "btn_C":     "🤟", "btn_D":     "🤙", "start": "👍",
    "reposo":    "🖐 ",
}

# ── Teclado ───────────────────────────────────────────────────────────
kb         = Controller()
active_key = None
_tap_lock  = threading.Lock()
_last_tap  = {}

def _safe_press(k):
    try: kb.press(k)
    except Exception: pass

def _safe_release(k):
    try: kb.release(k)
    except Exception: pass

def release_active():
    global active_key
    if active_key is not None:
        _safe_release(active_key)
        active_key = None

def _do_tap(key, gesto):
    with _tap_lock:
        _safe_press(key)
        time.sleep(TAP_DURATION)
        _safe_release(key)
        _last_tap[gesto] = time.time()

def execute_gesture(gesto):
    global active_key
    key = KEY_MAP.get(gesto)
    if key is None:
        release_active()
        return
    if gesto in HOLD_GESTURES:
        if active_key != key:
            release_active()
            _safe_press(key)
            active_key = key
    elif gesto in TAP_GESTURES:
        if time.time() - _last_tap.get(gesto, 0) > TAP_COOLDOWN:
            if not _tap_lock.locked():
                threading.Thread(target=_do_tap, args=(key, gesto), daemon=True).start()

# ── Serial ────────────────────────────────────────────────────────────
def abrir_serial():
    try:
        s = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print(f"✓ ESP32 en {SERIAL_PORT}\n")
        return s
    except serial.SerialException:
        print("✗ ESP32 no encontrado en COM4.")
        raise SystemExit(1)

# ── Parser ────────────────────────────────────────────────────────────
_LINE_RE = re.compile(r"^(\w+)\s*:\s*(\w+)$")

def parse_block(lines):
    estado = {}
    for line in lines:
        m = _LINE_RE.match(line.strip())
        if m:
            estado[m.group(1)] = m.group(2)
    return estado

def block_to_gestures(estado):
    """Devuelve lista de gestos activos. Permite combo pulgar+medio simultáneo."""
    gestos = []

    # Combo permitido: pulgar + medio activos juntos (moverse + disparar)
    pulgar_st = estado.get("pulgar", "reposo")
    medio_st  = estado.get("medio",  "reposo")

    if pulgar_st in ("normal", "ultra") and medio_st in ("normal", "ultra"):
        g_pulgar = FINGER_GESTURE["pulgar"].get(pulgar_st)
        g_medio  = FINGER_GESTURE["medio"].get(medio_st)
        if g_pulgar: gestos.append(g_pulgar)
        if g_medio:  gestos.append(g_medio)
        return gestos

    # Caso normal: un solo dedo activo (prioridad: pulgar > indice > medio > anular > menique)
    for dedo in ("pulgar", "indice", "medio", "anular", "menique"):
        st = estado.get(dedo, "reposo")
        if st in ("normal", "ultra"):
            g = FINGER_GESTURE.get(dedo, {}).get(st)
            if g:
                gestos.append(g)
            return gestos

    return gestos  # vacío = reposo

# ── Control pausa/resume ──────────────────────────────────────────────
control_activo = False

def on_key_press(key):
    global control_activo
    try:
        ch = key.char.lower() if hasattr(key, 'char') and key.char else None
        if ch == 'i':
            control_activo = True
            release_active()
            print("\n  ▶ Control ACTIVO\n")
        elif ch == 'o':
            control_activo = False
            release_active()
            print("\n  ⏸ Control PAUSADO — presiona [I] para reanudar\n")
    except Exception:
        pass

KbListener(on_press=on_key_press).start()

# ── Loop principal ────────────────────────────────────────────────────
ser = abrir_serial()

print("  [I] activar  |  [O] pausar  |  Ctrl+C salir")
print("  ⏸ Esperando [I]...\n")

current_lines = []
last_gesto    = "reposo"

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
                estado  = parse_block(current_lines)
                gestos  = block_to_gestures(estado)

                if control_activo:
                    if not gestos:
                        # reposo
                        if last_gesto in HOLD_GESTURES:
                            release_active()
                        last_gesto = "reposo"
                    else:
                        for g in gestos:
                            execute_gesture(g)
                        label = "+".join(gestos)
                        if label != last_gesto:
                            print(f"\r  {EMOJIS.get(gestos[0],'  ')} {label:<18}", end="", flush=True)
                            last_gesto = label

                current_lines = []
        else:
            current_lines.append(line)

except KeyboardInterrupt:
    release_active()
    ser.close()
    print("\n\nSaliendo...")
