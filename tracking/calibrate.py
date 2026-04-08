import cv2
import numpy as np
import glob
import os
import subprocess
import json

CAM1_SLOZKA = "velkadira//1_kamera"
CAM2_SLOZKA = "10kc/2_kamera"

# Skutečná vnitřní výška akvária v cm (změř pravítkem od hladiny po dno)
VYSKA_AKVARIA_CM = 38.0  # <-- UPRAV

ZOBRAZ_SIRKA = 1000  # šířka náhledu v px — zvětši pokud je moc malé

def aplikuj_rotaci(frame, rot):
    if rot == 90:    return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if rot in (270, -90): return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if rot == 180:   return cv2.rotate(frame, cv2.ROTATE_180)
    return frame

def ziskej_rotaci(video_path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", video_path],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for stream in json.loads(r.stdout).get("streams", []):
                rot = stream.get("tags", {}).get("rotate")
                if rot:
                    return int(rot)
    except Exception:
        pass
    return None

def kalibruj_kameru(video_path, nazev_kamery):
    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print(f"CHYBA: Nelze načíst {video_path}")
        return None

    # Aplikuj rotaci — stejně jako trim_videa.py
    rotace = ziskej_rotaci(video_path)
    frame  = aplikuj_rotaci(frame, rotace)

    # Přepočítej rozměry PO rotaci — tohle byl bug
    h, w   = frame.shape[:2]
    scale  = ZOBRAZ_SIRKA / w

    clicks = []
    img    = frame.copy()

    # Instrukce — dole aby nezakrývaly video (stejně jako trim_videa)
    cv2.rectangle(img, (0, h - 90), (w, h), (0, 0, 0), -1)
    cv2.putText(img, f"KALIBRACE: {nazev_kamery}", (10, h - 68),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(img, "1. Klikni na HORNI vnitrni okraj  2. Klikni na DOLNI okraj",
                (10, h - 42), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
    cv2.putText(img, "ESC = zrusit",
                (10, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

    nazev_okna = f"Kalibrace | {nazev_kamery}"

    def on_click(event, x, y, flags, _):
        if event != cv2.EVENT_LBUTTONDOWN or len(clicks) >= 2:
            return
        # Přepočet z náhledu na originál
        orig_x = int(x / scale)
        orig_y = int(y / scale)
        clicks.append((orig_x, orig_y))

        if len(clicks) == 1:
            cv2.line(img, (0, orig_y), (w, orig_y), (0, 255, 255), 3)
            cv2.putText(img, f"HORNI: y={orig_y}",
                        (10, max(orig_y - 12, 30)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)
        else:
            cv2.line(img, (0, orig_y), (w, orig_y), (0, 165, 255), 3)
            cv2.putText(img, f"DOLNI: y={orig_y}",
                        (10, min(orig_y + 45, h - 100)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 3)
            y1 = clicks[0][1]
            x_mid = w // 2
            cv2.line(img, (x_mid, y1), (x_mid, orig_y), (0, 255, 0), 3)
            px = abs(orig_y - y1)
            cv2.putText(img, f"{px} px = {VYSKA_AKVARIA_CM} cm",
                        (x_mid + 15, (y1 + orig_y) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)

        # Zobraz aktualizovaný zmenšený náhled
        nahled = cv2.resize(img, (ZOBRAZ_SIRKA, int(h * scale)))
        cv2.imshow(nazev_okna, nahled)

    cv2.namedWindow(nazev_okna, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(nazev_okna, on_click)
    nahled = cv2.resize(img, (ZOBRAZ_SIRKA, int(h * scale)))
    cv2.imshow(nazev_okna, nahled)

    while len(clicks) < 2:
        key = cv2.waitKey(30)
        if key == 27:
            cv2.destroyWindow(nazev_okna)
            return None

    cv2.waitKey(1200)
    cv2.destroyWindow(nazev_okna)

    y1 = clicks[0][1]
    y2 = clicks[1][1]
    px_vyska = abs(y2 - y1)

    if px_vyska == 0:
        print("CHYBA: Oba body jsou na stejné výšce.")
        return None

    m_per_px = (VYSKA_AKVARIA_CM / 100.0) / px_vyska

    return {
        "m_per_px":        m_per_px,
        "px_vyska":        px_vyska,
        "zavora_top":      min(y1, y2),
        "ignoruj_bottom":  max(y1, y2),
    }

# =========================================================
# HLAVNÍ KÓD
# =========================================================

print("=" * 60)
print("KALIBRACE KAMER")
print(f"Vyska akvaria: {VYSKA_AKVARIA_CM} cm  (uprav VYSKA_AKVARIA_CM nahore)")
print("=" * 60)

videa1 = sorted(glob.glob(os.path.join(CAM1_SLOZKA, "*.mp4")))
videa2 = sorted(glob.glob(os.path.join(CAM2_SLOZKA, "*.mp4")))

if not videa1: print(f"CHYBA: Zadna videa v '{CAM1_SLOZKA}'"); exit(1)
if not videa2: print(f"CHYBA: Zadna videa v '{CAM2_SLOZKA}'"); exit(1)

print(f"\nKamera 1: {videa1[0]}")
vysl1 = kalibruj_kameru(videa1[0], "Kamera 1 (predni)")

print(f"\nKamera 2: {videa2[0]}")
vysl2 = kalibruj_kameru(videa2[0], "Kamera 2 (bocni)")

print("\n" + "=" * 60)
print("VYSLEDKY — zkopiruj do analyze_mince.py:")
print("=" * 60)

if vysl1:
    print(f"\n# Kamera 1  ({VYSKA_AKVARIA_CM} cm = {vysl1['px_vyska']} px)")
    print(f"CAM1_MPX_X = {vysl1['m_per_px']:.8f}")
    print(f"CAM1_MPX_Y = {vysl1['m_per_px']:.8f}")
    print(f"# Hranice (pouzij pri nastavovani v analyze_mince.py):")
    print(f"#   horni okraj = {vysl1['zavora_top']} px")
    print(f"#   dolni okraj = {vysl1['ignoruj_bottom']} px")

if vysl2:
    print(f"\n# Kamera 2  ({VYSKA_AKVARIA_CM} cm = {vysl2['px_vyska']} px)")
    print(f"CAM2_MPX_X = {vysl2['m_per_px']:.8f}")
    print(f"CAM2_MPX_Y = {vysl2['m_per_px']:.8f}")
    print(f"# Hranice:")
    print(f"#   horni okraj = {vysl2['zavora_top']} px")
    print(f"#   dolni okraj = {vysl2['ignoruj_bottom']} px")

if vysl1 and vysl2:
    r = vysl1['m_per_px'] / vysl2['m_per_px']
    print(f"\n# Pomer kamera1/kamera2 = {r:.3f}  (idealne ~1.0)")
    if abs(r - 1.0) > 0.3:
        print("# POZOR: velky rozdil — zkontroluj ze jsi klikal na vnitrni okraje!")

print("=" * 60)