import socket
import struct
import numpy as np
from ultralytics import YOLO

# --- 1) Charger le modèle YOLO ---
model = YOLO("best.pt")

HOST = '127.0.0.1'
PORT = 5050

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(1)
print("Serveur YOLO démarré. En attente de Webots...")

conn, addr = server.accept()
print("Connexion Webots :", addr)

try:
    while True:
        # --- 2) Recevoir largeur, hauteur et taille image (4 bytes chacun, network order) ---
        w_bytes = conn.recv(4)
        h_bytes = conn.recv(4)
        size_bytes = conn.recv(4)
        if not w_bytes or not h_bytes or not size_bytes:
            print("Webots déconnecté ou données incomplètes")
            break

        w = struct.unpack("!I", w_bytes)[0]
        h = struct.unpack("!I", h_bytes)[0]
        size = struct.unpack("!I", size_bytes)[0]

        print(f"Image reçue : w={w}, h={h}, size={size}")

        # --- 3) Recevoir image brute ---
        data = b""
        while len(data) < size:
            packet = conn.recv(size - len(data))
            if not packet:
                break
            data += packet

        if len(data) != size:
            print(f"Erreur: taille image reçue {len(data)} != attendue {size}")
            break

        # --- 4) Reconstruction image RGB ---
        img_np = np.frombuffer(data, dtype=np.uint8)
        try:
            img_np = img_np.reshape((h, w, 3))
        except ValueError:
            print(f"Erreur reshape: data size={img_np.size}, attendu {(h*w*3)}")
            break

        # --- 5) Détection YOLO ---
        results = model.predict(img_np, verbose=False)
        print("Résultats YOLO :", results)

        # --- 6) Extraction de l'angle depuis OBB avec correction 0-180° ---
        angle_deg = -999.0
        obb = results[0].obb
        if obb is not None and len(obb.xywhr) > 0:
            first_obb = obb.xywhr.cpu().numpy()[0]  # [x_center, y_center, w, h, rotation]
            rotation_rad = first_obb[4]
            w_box, h_box = first_obb[2], first_obb[3]

            # Conversion en degrés
            angle_deg = float(np.degrees(rotation_rad))

            # Correction si la boîte est “verticale”
            if h_box > w_box:
                angle_deg += 90

            # Normaliser dans [0, 180]
            if angle_deg > 180:
                angle_deg -= 180

            print("Angle corrigé =", angle_deg)

        # --- 7) Envoyer l'angle en double à Webots ---
        conn.sendall(struct.pack("d", angle_deg))
        print(f"Angle envoyé = {angle_deg:.2f}°\n")

finally:
    conn.close()
    server.close()
    print("Serveur fermé")
