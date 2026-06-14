"""
Manuel Assist — Teclado Humano (WiFi UDP)
Uso: python teclado_humano.py

Handshake automático con ESP32:
  ESP32 → broadcast "MA_HELLO,<IP>"
  PC    → responde  "MA_PC,<PC_IP>"  al ESP32

Formato paquetes entrantes:
  "pulgar:activo"   "menique:reposo"   "SYS:CAMBIO_DE_MODO"  etc.

Modos (cambia levantando los 5 dedos a la vez):
  0 = teclado   → escribe letras a-z con dedos
  1 = cursor    → (próximamente)
  2 = numeros   → (próximamente)

Mapeo letras (modo teclado):
  Pulgar : a b c d e f        (×1 ×2 ×3 ×4 ×5 ×6)
  Indice : g h i j k l        (×1 ×2 ×3 ×4 ×5 ×6)
  Medio  : m n ñ o p          (×1 ×2 ×3 ×4 ×5)
  Anular : q r s t u          (×1 ×2 ×3 ×4 ×5)
  Menique: v w x y z          (×1 ×2 ×3 ×4 ×5)

Confirmación letra:
  - 2 segundos en reposo      → escribe la letra pendiente
  - Cambiar a otro dedo       → confirma la anterior, empieza la nueva

Controles (no escriben texto):
  [F5]   activar teclado
  [F6]   pausar teclado
  Ctrl+C salir
"""

import socket
import time
import threading
from pynput.keyboard import Controller, Key, Listener as KbListener

# ── Puertos UDP ───────────────────────────────────────────────────────
PC_PORT  = 5005   # PC escucha aquí (igual que firmware)
ESP_PORT = 5006   # ESP32 escucha aquí

# ── Modos ─────────────────────────────────────────────────────────────
MODOS = ["TECLADO", "CURSOR", "NUMEROS"]

# ── Mapeo letras ──────────────────────────────────────────────────────
LETTER_MAP = {
    "pulgar":  ['a', 'b', 'c', 'd', 'e', 'f'],
    "indice":  ['g', 'h', 'i', 'j', 'k', 'l'],
    "medio":   ['m', 'n', 'ñ', 'o', 'p'],
    "anular":  ['q', 'r', 's', 't', 'u'],
    "menique": ['v', 'w', 'x', 'y', 'z'],
}

DEDOS = ["menique", "anular", "medio", "indice", "pulgar"]

CONFIRM_DELAY = 2.0   # segundos en reposo para confirmar letra

# ── Teclado pynput ────────────────────────────────────────────────────
kb = Controller()

# ── Estado global ─────────────────────────────────────────────────────
modo_actual      = 0
pending_finger   = None
pending_count    = 0
all_reposo_since = None
finger_states    = {d: "reposo" for d in DEDOS}
control_activo   = False
esp_ip           = None
connected        = False
_lock            = threading.Lock()

# ── Utilidades ────────────────────────────────────────────────────────
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

def imprimir_mapa():
    print("  ┌─────────────────────────────────────────────┐")
    for dedo, letras in LETTER_MAP.items():
        fila = "  ".join(f"×{i+1}={l}" for i, l in enumerate(letras))
        print(f"  │  {dedo:<8} {fila}")
    print("  └─────────────────────────────────────────────┘")

def imprimir_modo():
    nombre = MODOS[modo_actual]
    print(f"\n  ══════════════════════════════════")
    print(f"   MODO: {nombre}  ({modo_actual+1}/{len(MODOS)})")
    if nombre == "TECLADO":
        imprimir_mapa()
    else:
        print(f"   (levanta 5 dedos para cambiar de modo)")
    print(f"  ══════════════════════════════════\n")

# ── Lógica de letra (modo TECLADO) ───────────────────────────────────
def letra_pendiente():
    if pending_finger is None or pending_count == 0:
        return None
    letras = LETTER_MAP.get(pending_finger, [])
    return letras[(pending_count - 1) % len(letras)] if letras else None

def confirmar():
    global pending_finger, pending_count, all_reposo_since
    letra = letra_pendiente()
    if letra:
        kb.type(letra)
        print(f"\n  ✓  '{letra}'  ({pending_finger} ×{pending_count})\n")
    pending_finger   = None
    pending_count    = 0
    all_reposo_since = None

def on_dedo_activo(dedo):
    global pending_finger, pending_count, all_reposo_since

    if modo_actual != 0:
        return   # solo procesamos letras en modo TECLADO

    all_reposo_since = None

    if dedo == pending_finger:
        pending_count += 1
    else:
        if pending_finger is not None:
            confirmar()
        pending_finger = dedo
        pending_count  = 1

    letra  = letra_pendiente()
    letras = LETTER_MAP.get(pending_finger, [])
    print(
        f"\r  {pending_finger} ×{pending_count} → '{letra}'  "
        f"[{'  '.join(letras)}]  (2s reposo para confirmar)    ",
        end="", flush=True
    )

def on_dedo_reposo():
    global all_reposo_since
    todos = all(v == "reposo" for v in finger_states.values())
    if todos and pending_finger is not None:
        if all_reposo_since is None:
            all_reposo_since = time.time()

def check_confirm_timer():
    global all_reposo_since
    if (all_reposo_since is not None
            and pending_finger is not None
            and time.time() - all_reposo_since >= CONFIRM_DELAY):
        confirmar()

# ── Procesador de paquetes UDP ────────────────────────────────────────
def procesar_paquete(data: str):
    global modo_actual, finger_states, connected, esp_ip

    data = data.strip()

    # Sistema
    if data.startswith("SYS:"):
        msg = data[4:]
        if msg == "CAMBIO_DE_MODO":
            modo_actual = (modo_actual + 1) % len(MODOS)
            imprimir_modo()
        elif msg == "CALIBRACION_OK":
            print("\n  ✓ Calibración completada\n")
        elif msg == "SISTEMA_LISTO":
            print("  ✓ ESP32 listo — usa el guante\n")
        else:
            print(f"\n  [SYS] {msg}")
        return

    # Dato de dedo: "pulgar:activo" / "menique:reposo"
    if ":" in data:
        partes = data.split(":", 1)
        if len(partes) == 2:
            dedo, estado = partes[0].strip(), partes[1].strip()
            if dedo in finger_states:
                prev = finger_states[dedo]
                finger_states[dedo] = estado
                if not control_activo:
                    return
                with _lock:
                    if prev == "reposo" and estado == "activo":
                        on_dedo_activo(dedo)
                    elif estado == "reposo":
                        on_dedo_reposo()

# ── UDP: escucha + handshake ──────────────────────────────────────────
def udp_loop():
    global connected, esp_ip

    pc_ip = get_local_ip()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", PC_PORT))
    sock.settimeout(0.1)

    print(f"  PC IP: {pc_ip}  — esperando ESP32 en puerto {PC_PORT}...")

    while True:
        try:
            data, addr = sock.recvfrom(256)
            msg = data.decode(errors="ignore").strip()

            # Handshake discovery
            if msg.startswith("MA_HELLO,"):
                esp_ip_str = msg[9:].strip()
                if not connected:
                    esp_ip = esp_ip_str
                    respuesta = f"MA_PC,{pc_ip}"
                    sock.sendto(respuesta.encode(), (esp_ip, ESP_PORT))
                    connected = True
                    print(f"\n  ✓ ESP32 conectado ({esp_ip})\n")
                continue

            # Datos normales
            if connected:
                procesar_paquete(msg)

        except socket.timeout:
            pass
        except Exception as e:
            print(f"\n  [UDP error] {e}")

# ── Control pausa/resume ──────────────────────────────────────────────
def on_key_press(key):
    global control_activo
    try:
        if key == Key.f5:
            control_activo = True
            print("\n  ▶ Teclado ACTIVO\n")
            imprimir_modo()
        elif key == Key.f6:
            control_activo = False
            print("\n  ⏸ Teclado PAUSADO — presiona [F5] para reanudar\n")
    except Exception:
        pass

# ── Main ──────────────────────────────────────────────────────────────
print("=" * 50)
print("  Manuel Assist — Teclado Humano (WiFi UDP)")
print("=" * 50)
print("  [F5] activar  |  [F6] pausar  |  Ctrl+C salir\n")
print("  Abre el Bloc de Notas, haz clic en él, luego [F5]\n")

KbListener(on_press=on_key_press).start()

hilo_udp = threading.Thread(target=udp_loop, daemon=True)
hilo_udp.start()

try:
    while True:
        with _lock:
            check_confirm_timer()
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\n\nSaliendo...")
