import cv2
import numpy as np

# =========================================================
# KONFIGURACE PRO VÝPOČET RYCHLOSTI
# =========================================================

VIDEO_PATH = "velkadira/1_kamera/velkadira11.mp4"  # <--- ZDE NASTAV CESTU K VIDEU
FPS = 60.0
MPX_Y = 0.00061889  # Kalibrace: Metrů na pixel v ose Y (z tvého hlavního skriptu)

# =========================================================

def ziskej_rotaci(video_path):
    try:
        import subprocess, json as js
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                            "-show_streams", video_path], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for stream in js.loads(r.stdout).get("streams", []):
                rot = stream.get("tags", {}).get("rotate")
                if rot: return int(rot)
    except: pass
    return None

def aplikuj_rotaci(frame, rot):
    if rot == 90:        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if rot in (270,-90): return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if rot == 180:       return cv2.rotate(frame, cv2.ROTATE_180)
    return frame

def mereni_rychlosti(video_path):
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rotace = ziskej_rotaci(video_path)

    # Detekce rozlišení monitoru pro správné zobrazení okna
    try:
        import tkinter as tk
        _root = tk.Tk(); _root.withdraw()
        SIRKA_OKNA = _root.winfo_screenwidth()
        VYSKA_OKNA = _root.winfo_screenheight()
        _root.destroy()
    except:
        SIRKA_OKNA, VYSKA_OKNA = 1920, 1080

    points = [] # Bude obsahovat [ (frame_idx, orig_y), (frame_idx, orig_y) ]

    nazev_okna = "Mereni ustalene rychlosti"
    cv2.namedWindow(nazev_okna, cv2.WINDOW_AUTOSIZE)

    # Proměnné pro scaling
    scale = 1.0

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(points) < 2:
                orig_y = int(y / scale)
                points.append((frame_idx, orig_y))

    cv2.setMouseCallback(nazev_okna, on_click)

    frame_idx = 0
    
    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret: break
        
        frame = aplikuj_rotaci(frame, rotace)
        h, w = frame.shape[:2]
        
        scale_w = SIRKA_OKNA / w
        scale_h = (VYSKA_OKNA - 100) / h 
        scale   = min(scale_w, scale_h)

        dbg = frame.copy()
        
        # Vykreslení naklikaných bodů
        if len(points) >= 1:
            y1_scaled = int(points[0][1] * scale)
            cv2.circle(dbg, (w//2, points[0][1]), 10, (0, 255, 0), -1)
            cv2.line(dbg, (0, points[0][1]), (w, points[0][1]), (0, 255, 0), 2)
        if len(points) == 2:
            y2_scaled = int(points[1][1] * scale)
            cv2.circle(dbg, (w//2, points[1][1]), 10, (0, 0, 255), -1)
            cv2.line(dbg, (0, points[1][1]), (w, points[1][1]), (0, 0, 255), 2)

        # UI Texty
        cv2.rectangle(dbg, (0, h-120), (w, h), (255,255,255), -1)
        cv2.putText(dbg, f"Snimek: {frame_idx}/{total_frames}  |  Oznaceno bodu: {len(points)}/2", (10, h-85), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,0), 2)
        cv2.putText(dbg, "[A]/[D] = Vzad/Vpred po 1 sn.  |  [W]/[S] = Skok po 10 sn.", (10, h-55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50,50,50), 1)
        cv2.putText(dbg, "KLIK = oznacit minci  |  [R] = smazat body  |  [Q] = Ukoncit", (10, h-25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50,50,50), 1)

        # Pokud máme 2 body, zobrazíme výsledek
        if len(points) == 2:
            f1, y1 = points[0]
            f2, y2 = points[1]
            
            # Aby výpočet fungoval i když to naklikáš pozpátku
            if f1 > f2:
                f1, f2 = f2, f1
                y1, y2 = y2, y1

            frames_diff = f2 - f1
            time_diff = frames_diff / FPS
            pixel_diff = abs(y2 - y1)
            dist_m = pixel_diff * MPX_Y
            
            if time_diff > 0:
                speed_m_s = dist_m / time_diff
                speed_cm_s = speed_m_s * 100
                cv2.putText(dbg, f"VYSLEDEK: {speed_m_s:.3f} m/s ({speed_cm_s:.1f} cm/s)", (w//2 - 200, h-85), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 200), 3)

        small = cv2.resize(dbg, (int(w*scale), int(h*scale)))
        cv2.imshow(nazev_okna, small)

        key = cv2.waitKey(0) & 0xFF
        
        if key == ord('d'): frame_idx = min(frame_idx + 1, total_frames - 1)
        elif key == ord('a'): frame_idx = max(frame_idx - 1, 0)
        elif key == ord('s'): frame_idx = min(frame_idx + 10, total_frames - 1)
        elif key == ord('w'): frame_idx = max(frame_idx - 10, 0)
        elif key == ord('r'): points = [] # Reset bodů
        elif key == ord('q') or key == 27: break # Konec

    cap.release()
    cv2.destroyAllWindows()

    if len(points) == 2:
        f1, y1 = points[0]; f2, y2 = points[1]
        time_diff = abs(f2 - f1) / FPS
        speed_m_s = (abs(y2 - y1) * MPX_Y) / time_diff if time_diff > 0 else 0
        print("\n" + "="*40)
        print(" VYSLEDKY MERENI")
        print("="*40)
        print(f" Startovni snimek: {min(f1, f2)}")
        print(f" Koncovy snimek:   {max(f1, f2)}")
        print(f" Ubehly cas:       {time_diff:.4f} s")
        print(f" Ujeta draha:      {(abs(y2 - y1) * MPX_Y * 100):.2f} cm")
        print(f" PRUMERNA RYCHLOST:{speed_m_s:.3f} m/s ({speed_m_s * 100:.1f} cm/s)")
        print("="*40 + "\n")

if __name__ == "__main__":
    mereni_rychlosti(VIDEO_PATH)