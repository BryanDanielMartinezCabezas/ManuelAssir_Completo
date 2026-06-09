"""
Manuel Assist — Receptor Neo Geo (NeoRageX 5.2a)
Uso: python receptor_neogeo.py   (cierra app.py antes)

Teclas NeoRageX Player 1 (default):
  reposo → —   btn_A → Z   btn_B → X   btn_C → A   btn_D → S
  arriba → ↑   abajo → ↓   derecha → →   izquierda → ←   start → Enter

Controles en consola:
  [I]      iniciar / detener simulación en bucle
  Ctrl+C   salir
"""

import json, pickle, re, time, threading
import numpy as np
import torch
import torch.nn as nn
import serial, serial.tools.list_ports
from pathlib import Path
from collections import deque
from pynput.keyboard import Controller, Key, KeyCode, Listener as KbListener

# ══════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════
SERIAL_PORT    = "COM4"
BAUD_RATE      = 115200
CONF_THRESHOLD = 0.70
STABLE_NEEDED  = 2
TAP_DURATION   = 0.08
TAP_COOLDOWN   = 0.25
FRAME_TIMEOUT  = 0.5

KEY_MAP = {
    "btn_A":     KeyCode.from_char('z'),
    "btn_B":     KeyCode.from_char('x'),
    "btn_C":     KeyCode.from_char('a'),
    "btn_D":     KeyCode.from_char('s'),
    "arriba":    Key.up,
    "abajo":     Key.down,
    "derecha":   Key.right,
    "izquierda": Key.left,
    "start":     Key.enter,
    "reposo":    None,
}
HOLD_GESTURES = {"arriba", "abajo", "derecha", "izquierda"}
TAP_GESTURES  = {"btn_A", "btn_B", "btn_C", "btn_D", "start"}

SIM_SEQUENCE = [
    ("reposo", 1.0), ("arriba", 1.2), ("abajo", 1.2),
    ("izquierda", 1.2), ("derecha", 1.2), ("btn_A", 0.8),
    ("btn_B", 0.8), ("btn_C", 0.8), ("btn_D", 0.8),
    ("start", 0.8), ("reposo", 0.5),
]
EMOJIS = {
    "reposo": "🖐 ", "btn_A": "☝ ", "btn_B": "✌ ",
    "btn_C":  "🤟", "btn_D": "🤙", "arriba": "⬆ ",
    "abajo":  "⬇ ", "derecha": "➡ ", "izquierda": "⬅ ", "start": "👍",
}
LABEL = {
    "reposo": "reposo   ", "btn_A": "BTN A    ", "btn_B": "BTN B    ",
    "btn_C":  "BTN C    ", "btn_D": "BTN D    ", "arriba": "ARRIBA   ",
    "abajo":  "ABAJO    ", "derecha": "DERECHA  ", "izquierda": "IZQUIERDA", "start": "START    ",
}

# ══════════════════════════════════════════════════════
#  MODELO
# ══════════════════════════════════════════════════════
BASE = Path(__file__).parent
CHANNEL_NAMES = {2: "pulgar", 3: "indice", 4: "medio", 5: "anular", 6: "menique"}

def load_model():
    try:
        with open(BASE / "metadata.json") as f:
            meta = json.load(f)
        with open(BASE / "scaler.pkl", "rb") as f:
            scaler = pickle.load(f)
        clases = meta["clases"]; window_size = meta["window_size"]
        input_size = meta["input_size"]; features = meta["features"]

        class MLP(nn.Module):
            def __init__(self):
                super().__init__()
                self.net = nn.Sequential(
                    nn.Linear(input_size, 128),
                    nn.BatchNorm1d(128), nn.ReLU(), nn.Dropout(0.3),
                    nn.Linear(128, 64),
                    nn.BatchNorm1d(64), nn.ReLU(), nn.Dropout(0.2),
                    nn.Linear(64, len(clases)),
                )
            def forward(self, x): return self.net(x)

        mlp = MLP()
        mlp.load_state_dict(torch.load(BASE / "modelo.pth", map_location="cpu"))
        mlp.eval()
        print(f"✓ Modelo cargado — {len(clases)} clases: {clases}")
        print(f"  Ventana: {window_size} frames | {input_size} features\n")
        return mlp, scaler, clases, window_size, input_size, features, True
    except FileNotFoundError as e:
        print(f"⚠  Sin modelo ({e.name})\n")
        return None, None, [], 1, 0, [], False

model, scaler, CLASES, WINDOW_SIZE, INPUT_SIZE, FEATURES, MODEL_READY = load_model()

# ══════════════════════════════════════════════════════
#  SERIAL
# ══════════════════════════════════════════════════════
def abrir_serial():
    # Primero intenta el puerto fijo (sin WMI)
    try:
        s = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.02)
        print(f"✓ ESP32 en {SERIAL_PORT}\n")
        return s
    except serial.SerialException:
        pass
    # Solo si falla, escaneo WMI una única vez
    for p in serial.tools.list_ports.comports():
        if any(x in p.description for x in ("CP210", "CH340", "FTDI", "USB Serial")):
            try:
                s = serial.Serial(p.device, BAUD_RATE, timeout=0.02)
                print(f"✓ ESP32 en {p.device}\n")
                return s
            except serial.SerialException:
                continue
    print("✗ ESP32 no encontrado. Conecta el cable USB.")
    raise SystemExit(1)

# ══════════════════════════════════════════════════════
#  TECLADO
# ══════════════════════════════════════════════════════
kb = Controller()
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
        _safe_release(active_key); active_key = None

def _do_tap(key, gesto):
    with _tap_lock:
        _safe_press(key); time.sleep(TAP_DURATION); _safe_release(key)
        _last_tap[gesto] = time.time()

def execute_gesture(gesto):
    global active_key
    key = KEY_MAP.get(gesto)
    if key is None:
        release_active(); return
    if gesto in HOLD_GESTURES:
        if active_key != key:
            release_active(); _safe_press(key); active_key = key
    elif gesto in TAP_GESTURES:
        if time.time() - _last_tap.get(gesto, 0) > TAP_COOLDOWN:
            if not _tap_lock.locked():
                threading.Thread(target=_do_tap, args=(key, gesto), daemon=True).start()

# ══════════════════════════════════════════════════════
#  INFERENCIA
# ══════════════════════════════════════════════════════
_LINE_RE = re.compile(
    r"CH=(\d+)\s+AX=([-\d.]+)\s+AY=([-\d.]+)\s+AZ=([-\d.]+)"
    r"\s+GX=([-\d.]+)\s+GY=([-\d.]+)\s+GZ=([-\d.]+)"
)

def parse(line):
    m = _LINE_RE.match(line.strip())
    if m:
        return int(m.group(1)), [float(m.group(i)) for i in range(2, 8)]
    return None, None

def frame_to_vector(frame):
    row = {}
    for ch, name in sorted(CHANNEL_NAMES.items()):
        vals = frame.get(ch, [0.0] * 6)
        for i, ax in enumerate(["ax","ay","az","gx","gy","gz"]):
            row[f"{name}_{ax}"] = vals[i]
    return [row[f] for f in FEATURES]

def predict(buf):
    try:
        vec = []
        for fr in buf: vec.extend(frame_to_vector(fr))
        X = scaler.transform(np.array(vec, dtype=np.float32).reshape(1, -1)).astype(np.float32)
        with torch.no_grad():
            probs = torch.softmax(model(torch.tensor(X)), dim=1)[0]
            conf, idx = probs.max(0)
        return CLASES[idx.item()], conf.item()
    except Exception:
        return "reposo", 0.0

# ══════════════════════════════════════════════════════
#  SIMULACIÓN
# ══════════════════════════════════════════════════════
sim_running = False

def run_simulation():
    global sim_running
    print("\n  ╔══════════════════════════════╗")
    print(  "  ║  SIMULACIÓN EN BUCLE  [I]    ║")
    print(  "  ║  Presiona [I] para detener  ║")
    print(  "  ╚══════════════════════════════╝\n")
    while sim_running:
        for gesto, dur in SIM_SEQUENCE:
            if not sim_running: break
            key   = KEY_MAP.get(gesto)
            key_s = str(key).replace("Key.", "").replace("'", "") if key else "—"
            print(f"  {EMOJIS.get(gesto,'  ')} {LABEL.get(gesto, gesto)}  [{key_s}]", flush=True)
            execute_gesture(gesto)
            deadline = time.time() + dur
            while sim_running and time.time() < deadline:
                time.sleep(0.05)
    release_active()
    print("\n  ✓ Simulación detenida\n")

def on_key_press(key):
    global sim_running
    try:
        if key == KeyCode.from_char('i'):
            if not sim_running:
                sim_running = True
                threading.Thread(target=run_simulation, daemon=True).start()
            else:
                sim_running = False
    except Exception:
        pass

KbListener(on_press=on_key_press).start()

# ══════════════════════════════════════════════════════
#  LOOP PRINCIPAL
# ══════════════════════════════════════════════════════
ser = abrir_serial()

print("  [I] simular  |  Ctrl+C salir\n")

current_frame  = {}
last_ch        = None
frame_start_ts = time.time()
frame_buffer   = deque(maxlen=max(WINDOW_SIZE, 1))
last_gesture   = None
stable_count   = 0

try:
    while True:
        try:
            raw = ser.readline()
        except serial.SerialException as e:
            print(f"\n⚠ Serial perdido — reconectando...")
            time.sleep(1)
            ser = abrir_serial()
            continue

        if not raw:
            continue

        line = raw.decode(errors="ignore").strip()
        if not line or "NO_DETECTADO" in line:
            continue

        ch, vals = parse(line)
        if ch is None:
            continue

        now = time.time()

        if current_frame and (now - frame_start_ts) > FRAME_TIMEOUT:
            current_frame = {}; last_ch = None

        if last_ch is not None and ch <= last_ch and current_frame:
            if set(CHANNEL_NAMES.keys()).issubset(current_frame.keys()):
                frame_buffer.append(dict(current_frame))

                if not MODEL_READY:
                    pz = current_frame.get(2, [0]*6)[2]
                    iz = current_frame.get(3, [0]*6)[2]
                    print(f"\r  [sin modelo]  pulgar_az={pz:+.3f}  indice_az={iz:+.3f}   ", end="", flush=True)

                elif len(frame_buffer) == WINDOW_SIZE:
                    gesto, conf = predict(frame_buffer)

                    if conf >= CONF_THRESHOLD:
                        if gesto == last_gesture:
                            stable_count += 1
                        else:
                            stable_count = 1
                            last_gesture = gesto
                            if gesto in HOLD_GESTURES:
                                release_active()

                        if stable_count >= STABLE_NEEDED:
                            execute_gesture(gesto)
                            bar = "█" * int(conf * 20)
                            print(f"\r  {EMOJIS.get(gesto,'  ')} {LABEL.get(gesto, gesto)}  {conf*100:5.1f}%  [{bar:<20}]", end="", flush=True)
                    else:
                        if stable_count > 0:
                            release_active(); print()
                        stable_count = 0; last_gesture = None
                        print(f"\r  ?               {conf*100:5.1f}%  (baja confianza)        ", end="", flush=True)

            current_frame = {}; frame_start_ts = now

        if not current_frame:
            frame_start_ts = now
        current_frame[ch] = vals
        last_ch = ch

except KeyboardInterrupt:
    release_active()
    ser.close()
    print("\n\nSaliendo...")
