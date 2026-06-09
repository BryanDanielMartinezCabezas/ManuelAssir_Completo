import socket
import threading

DISCOVERY_PORT = 4210
DATA_PORT = 4211

def discovery_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", DISCOVERY_PORT))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    print(f"[DISCOVERY] Escuchando en UDP {DISCOVERY_PORT}...")

    while True:
        data, addr = sock.recvfrom(2048)
        msg = data.decode(errors="ignore")
        print(f"[DISCOVERY] {addr[0]}:{addr[1]} -> {msg}")

        if msg.startswith("HELLO_ESP32"):
            reply = "HELLO_LAPTOP|name=pc_python"
            sock.sendto(reply.encode(), addr)
            print(f"[DISCOVERY] Reply enviado a {addr[0]}")

def data_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", DATA_PORT))

    print(f"[DATA] Escuchando en UDP {DATA_PORT}...")

    while True:
        data, addr = sock.recvfrom(4096)
        msg = data.decode(errors="ignore")
        print(f"[SENSOR] {addr[0]} -> {msg}")

if __name__ == "__main__":
    t1 = threading.Thread(target=discovery_server, daemon=True)
    t2 = threading.Thread(target=data_server, daemon=True)

    t1.start()
    t2.start()

    print("Python listo. Esperando paquetes del ESP32...")
    while True:
        pass