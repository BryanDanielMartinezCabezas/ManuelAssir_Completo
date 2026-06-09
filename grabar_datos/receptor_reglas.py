"""
Manuel Assist — Receptor Neo Geo por REGLAS (propuesta Ovando)
Sin modelo ML. Calibración al arranque + umbrales de ángulo.
Uso: python receptor_reglas.py   (conecta el ESP32 por USB antes)

Controles:
  [C]      recalibrar sin reiniciar
  [I]      iniciar / detener simulación en bucle
  Ctrl+C   salir
"""

import math, time, threading, re
import serial, serial.tools.list_ports
from pynput.keyboard import Controller, Key, KeyCode, Listener as KbListener

# ══════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════
SERIAL_PORT  = "COM4"     # cambia si tu ESP32 aparece en otro puerto
BAUD_RATE    = 115200

UP_THRESH    = 35    # flexion% < esto  → dedo estirado / arriba
DOWN_THRESH  = 65    # flexion% > esto  → dedo doblado  / abajo
CAL_SECS     = 3     # segundos de captura por posición
STABLE_NEED  = 2     # tramas estables antes de ejecutar
TAP_DURATION = 0.08
TAP_COOLDOWN = 0.25

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

CHANNEL_NAMES = {2: "pulgar", 3: "indice", 4: "medio", 5: "anular", 6: "menique"}

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
SIM_SEQUENCE = [
    ("reposo",    1.0), ("arriba",    1.2), ("abajo",     1.2),
    ("izquierda", 1.2), ("derecha",   1.2), ("btn_A",     0.8),
    ("btn_B",     0.8), ("btn_C",     0.8), ("btn_D",     0.8),
    ("start",     0.8), ("reposo",    0.5),
]

# ══════════════════════════════════════════════════════
#  SERIAL — auto-detecta si SERIAL_PORT falla
# ══════════════════════════════════════════════════════
def abrir_serial():
    try:
        s = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.02)
        print(f"  ✓ ESP32 en {SERIAL_PORT}\n")
        return s
    except serial.SerialException:
        print(f"  ⚠ {SERIAL_PORT} no disponible — buscando ESP32...")
        for p in serial.tools.list_ports.comports():
            if any(x in p.description for x in ("CP210", "CH340", "FTDI", "USB Serial")):
                try:
                    s = serial.Serial(p.device, BAUD_RATE, timeout=0.02)
                    print(f"  ✓ ESP32 encontrado en {p.device}\n")
                    return s
                except serial.SerialException:
                    continue
        print("  ✗ No se encontró ESP32. Conecta el cable USB y vuelve a correr.")
        raise SystemExit(1)

# ══════════════════════════════════════════════════════
#  PARSEO
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

# ══════════════════════════════════════════════════════
#  ÁNGULO Y CALIBRACIÓN
# ══════════════════════════════════════════════════════
def calc_angle(ax, ay, az):
    return math.degrees(math.atan2(ay, math.sqrt(ax*ax + az*az)))

cal_open  = {}
cal_close = {}
frame_queue = []

def flexion_pct(ch, angle):
    o = cal_open.get(ch)
    c = cal_close.get(ch)
    if o is None or c is None or abs(c - o) < 0.5:
        return 50.0
    return max(0.0, min(100.0, (angle - o) / (c - o) * 100.0))

def collect_angles(secs):
    samples = {ch: [] for ch in CHANNEL_NAMES}
    t0 = time.time()
    while time.time() - t0 < secs:
        if frame_queue:
            frame = frame_queue.pop(0)
            for ch, vals in frame.items():
                samples[ch].append(calc_angle(*vals[:3]))
        time.sleep(0.01)
    return {ch: (sum(v)/len(v) if v else 0.0) for ch, v in samples.items()}

def run_calibration():
    global cal_open, cal_close
    print("\n  ┌─────────────────────────────────┐")
    print(  "  │        CALIBRACIÓN              │")
    print(  "  └─────────────────────────────────┘")
    print(f"\n  1/2  Extiende todos los dedos — mano ABIERTA")
    for i in range(CAL_SECS, 0, -1):
        print(f"       {i}...", flush=True); time.sleep(1)
    frame_queue.clear()
    cal_open = collect_angles(CAL_SECS)

    print(f"\n  2/2  Cierra el PUÑO — todos los dedos doblados")
    for i in range(CAL_SECS, 0, -1):
        print(f"       {i}...", flush=True); time.sleep(1)
    frame_queue.clear()
    cal_close = collect_angles(CAL_SECS)

    print("\n  ✓ Calibración lista:")
    for ch, name in sorted(CHANNEL_NAMES.items()):
        o = cal_open.get(ch, 0); c = cal_close.get(ch, 0)
        print(f"    {name:<8}  abierto={o:+6.1f}°  cerrado={c:+6.1f}°  rango={abs(c-o):.1f}°")
    print()

# ══════════════════════════════════════════════════════
#  REGLAS (prioridad: más dedos → más específico primero)
# ══════════════════════════════════════════════════════
def classify(flex):
    p  = flex.get(2, 50); i  = flex.get(3, 50)
    m  = flex.get(4, 50); an = flex.get(5, 50); me = flex.get(6, 50)

    i_up  = i  < UP_THRESH;  i_dn  = i  > DOWN_THRESH
    m_up  = m  < UP_THRESH;  m_dn  = m  > DOWN_THRESH
    an_up = an < UP_THRESH;  an_dn = an > DOWN_THRESH
    me_up = me < UP_THRESH;  me_dn = me > DOWN_THRESH
    p_up  = p  < UP_THRESH;  p_dn  = p  > DOWN_THRESH

    if i_dn and m_dn and an_dn and me_dn:                         return "abajo"
    if i_up and m_up and an_up and me_up:                         return "arriba"
    if i_up and m_up and an_dn and me_dn:                         return "derecha"
    if p_dn and i_up:                                             return "izquierda"
    if p_up and not i_up and not m_up:                            return "start"
    if i_up and not m_up and not an_up and not me_up:             return "btn_A"
    if m_up and not i_up and not an_up and not me_up:             return "btn_B"
    if an_up and not i_up and not m_up and not me_up:             return "btn_C"
    if me_up and not i_up and not m_up and not an_up:             return "btn_D"
    return "reposo"

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
        elif key == KeyCode.from_char('c'):
            threading.Thread(target=run_calibration, daemon=True).start()
    except Exception:
        pass

KbListener(on_press=on_key_press).start()

# ══════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════
ser = abrir_serial()

cal_thread = threading.Thread(target=run_calibration, daemon=True)
cal_thread.start()
cal_thread.join()

print("  [C] recalibrar  |  [I] simular  |  Ctrl+C salir\n")

# ══════════════════════════════════════════════════════
#  LOOP PRINCIPAL
# ══════════════════════════════════════════════════════
current_frame  = {}
last_ch        = None
frame_start_ts = time.time()
FRAME_TIMEOUT  = 0.5
last_gesture   = None
stable_count   = 0

try:
    while True:
        try:
            raw = ser.readline()
        except serial.SerialException as e:
            print(f"\n  ⚠ Serial perdido: {e} — reconectando...")
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
                frame_queue.append(dict(current_frame))

                flex = {c: flexion_pct(c, calc_angle(*v[:3])) for c, v in current_frame.items()}
                gesto = classify(flex)

                if gesto == last_gesture:
                    stable_count += 1
                else:
                    stable_count = 1
                    last_gesture = gesto
                    if gesto in HOLD_GESTURES:
                        release_active()

                if stable_count >= STABLE_NEED:
                    execute_gesture(gesto)
                    pct_str = " ".join(
                        f"{CHANNEL_NAMES[c][0].upper()}:{flex.get(c,50):3.0f}"
                        for c in sorted(CHANNEL_NAMES)
                    )
                    print(f"\r  {EMOJIS.get(gesto,'  ')} {LABEL.get(gesto,gesto)}  |  {pct_str}   ",
                          end="", flush=True)

            current_frame = {}; frame_start_ts = now

        if not current_frame:
            frame_start_ts = now
        current_frame[ch] = vals
        last_ch = ch

except KeyboardInterrupt:
    release_active()
    ser.close()
    print("\n\nSaliendo...")
