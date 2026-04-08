import cv2
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.collections import LineCollection
from mpl_toolkits.mplot3d import Axes3D
from scipy.signal import savgol_filter
from scipy.interpolate import interp1d
import os
import glob
import csv
import sys
import re
import json
import math
import argparse

# =========================================================
# KONFIGURACE (Zde vložte výsledky z kalibračního skriptu)
# =========================================================

# Cesty se přepíšou podle argumentu z příkazové řádky (viz __main__)
CAM1_SLOZKA  = "1_kamera"
CAM1_MPX_X = 0.00068223
CAM1_MPX_Y = 0.00068223

CAM2_SLOZKA  = "2_kamera"
CAM2_MPX_X = 0.00071295
CAM2_MPX_Y = 0.00071295

FPS_VIDEA           = 60.0
CHYBA_M             = 0.006
CHYBA_CM            = CHYBA_M * 100
HLOUBKA_AKVARIA_CM  = 38.0

# Velikost okna — detekuje rozlišení obrazovky automaticky
try:
    import tkinter as tk
    _root = tk.Tk(); _root.withdraw()
    SIRKA_OKNA = 1700
    VYSKA_OKNA = 900
    _root.destroy()
except Exception:
    SIRKA_OKNA = 1920
    VYSKA_OKNA = 1080

HMOTNOST_KG = {
    "default": 0.00843,
}
G = 9.81

CACHE_SOUBOR = "tracking_cache.json"

# =========================================================
# POMOCNÉ FUNKCE
# =========================================================

def ziskej_hmotnost(nazev):
    for k, v in HMOTNOST_KG.items():
        if k.lower() in nazev.lower():
            return v
    return HMOTNOST_KG["default"]

def vyhladj(arr):
    n = len(arr)
    win = min(11, n if n % 2 == 1 else n - 1)
    if win < 5: return arr.copy()
    return savgol_filter(arr, window_length=win, polyorder=min(3, win - 1))

def derivace(arr, time_s):
    dt = np.diff(time_s)
    v  = np.diff(vyhladj(arr)) / dt
    mu, sigma = np.mean(v), np.std(v)
    if sigma > 0:
        mask = np.abs(v - mu) > 3 * sigma
        if mask.any() and (~mask).sum() >= 2:
            v[mask] = np.interp(np.where(mask)[0], np.where(~mask)[0], v[~mask])
    return v

def _style_ax(ax):
    ax.set_facecolor('white')
    for s in ['top', 'right']: ax.spines[s].set_visible(False)
    for s in ['bottom', 'left']: ax.spines[s].set_color('black')
    ax.tick_params(colors='black')
    ax.grid(True, ls='--', lw=0.5, alpha=0.3, color='black')

def ziskej_rotaci(video_path):
    try:
        import subprocess, json as js
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", video_path],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for stream in js.loads(r.stdout).get("streams", []):
                rot = stream.get("tags", {}).get("rotate")
                if rot: return int(rot)
    except Exception:
        pass
    return None

def aplikuj_rotaci(frame, rot):
    if rot == 90:        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if rot in (270,-90): return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if rot == 180:       return cv2.rotate(frame, cv2.ROTATE_180)
    return frame

def nacti_cache():
    if os.path.exists(CACHE_SOUBOR):
        with open(CACHE_SOUBOR, 'r') as f:
            return json.load(f)
    return {}

def uloz_cache(cache):
    with open(CACHE_SOUBOR, 'w') as f:
        json.dump(cache, f)

# =========================================================
# AUTO-TRACKING (Čistý pohyb v lokálním okně, bez filtrů barev a jasu)
# =========================================================

def automaticky_track(video_path, rotace, nazev_kamery):
    """
    Nová strategie:
    1. Klikni na elektromagnet — určí X pozici pádu
    2. Čekej na pohyb PŘÍMO POD HLADINOU v úzkém X-pruhu
       (ne u elektromagnetu kde vlní voda)
    3. Sleduj minci frame diffem dolů
    """
    SEARCH_R  = 80    # px — oblast sledování po locku
    MAX_SKOK  = 150   # px — max skok mezi snímky
    X_TOL     = 80    # px — šířka X-pruhu kde čekáme na minci pod hladinou
    POHYB_MIN = 400   # px² — pohyb pod hladinou = mince přišla
    POHYB_POCET = 2   # snímky za sebou s pohybem = potvrzeno

    if "1" in nazev_kamery:
        zavora_top = 321
    else:
        zavora_top = 364

    # Pás pod hladinou kde čekáme na minci (ne na vlnění)
    WAIT_BAND_TOP = zavora_top + 10   # px pod hladinou
    WAIT_BAND_BOT = zavora_top + 120  # px pod hladinou

    # --- Krok 1: klikni na elektromagnet (jen pro X pozici) ---
    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None, None

    frame = aplikuj_rotaci(frame, rotace)
    h, w  = frame.shape[:2]
    scale = min(SIRKA_OKNA / w, (VYSKA_OKNA - 50) / h)
    center_x = w // 2
    click_pos = [None]

    img = frame.copy()
    cv2.line(img, (0, zavora_top), (w, zavora_top), (0, 0, 255), 2)
    cv2.line(img, (0, WAIT_BAND_BOT), (w, WAIT_BAND_BOT), (0, 200, 0), 1)
    cv2.putText(img, "HLADINA", (10, zavora_top - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.putText(img, "Klikni na MINCI u elektromagnetu (jen pro X pozici)",
                (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.putText(img, "Skript bude cekat az mince propluje touto oblasti",
                (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 200, 0), 2)

    nazev_okna = f"Oznac elektromagnet | {nazev_kamery}"

    def on_click(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN:
            orig_x = int(x / scale)
            orig_y = int(y / scale)
            click_pos[0] = (orig_x, orig_y)
            tmp = img.copy()
            # Nakresli X-pruh kde se čeká na minci
            x1 = max(0, orig_x - X_TOL)
            x2 = min(w, orig_x + X_TOL)
            cv2.rectangle(tmp, (x1, WAIT_BAND_TOP), (x2, WAIT_BAND_BOT),
                          (0, 255, 0), 2)
            cv2.circle(tmp, (orig_x, orig_y), 15, (0, 255, 0), 3)
            cv2.putText(tmp, "Zmackni klávesu",
                        (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 0), 2)
            cv2.imshow(nazev_okna, cv2.resize(tmp, (int(w*scale), int(h*scale))))

    cv2.namedWindow(nazev_okna, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(nazev_okna, on_click)
    cv2.imshow(nazev_okna, cv2.resize(img, (int(w*scale), int(h*scale))))

    while click_pos[0] is None:
        cv2.waitKey(30)
    cv2.waitKey(600)
    cv2.destroyWindow(nazev_okna)

    em_x, em_y = click_pos[0]
    print(f"  Elektromagnet: ({em_x}, {em_y}) — cekam na minci pod hladinou")

    # X-pruh pod hladinou kde čekáme
    wx1 = max(0, em_x - X_TOL)
    wx2 = min(w, em_x + X_TOL)

    # --- Krok 2: nauč pozadí ze statických snímků ---
    cap  = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    frame = aplikuj_rotaci(frame, rotace)
    h, w  = frame.shape[:2]
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # Ulož referenční snímek pod hladinou (bez mince)
    # Použijeme průměr prvních 5 snímků jako referenci
    refs = []
    for _ in range(5):
        ret, f = cap.read()
        if not ret: break
        f = aplikuj_rotaci(f, rotace)
        gray = cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5,5), 0)
        refs.append(gray[WAIT_BAND_TOP:WAIT_BAND_BOT, wx1:wx2].astype(np.float32))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    ref_gray = np.mean(refs, axis=0).astype(np.uint8) if refs else None

    kernel    = np.ones((5, 5), np.uint8)
    raw_x, raw_y = [], []
    locked    = False
    last_x    = em_x
    last_y    = WAIT_BAND_TOP + 10
    prev_gray = None
    pohyb_streak = 0
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        frame   = aplikuj_rotaci(frame, rotace)
        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        found_now = False

        if not locked:
            # Čekej na minci v pásu POD HLADINOU
            # Porovnej s referenčním snímkem (průměr prvních snímků)
            roi = blurred[WAIT_BAND_TOP:WAIT_BAND_BOT, wx1:wx2]

            if ref_gray is not None and roi.shape == ref_gray.shape:
                diff = cv2.absdiff(roi, ref_gray)
                _, diff_th = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
                pohyb_px = int(np.sum(diff_th > 0))
            else:
                pohyb_px = 0

            if pohyb_px > POHYB_MIN:
                pohyb_streak += 1
            else:
                pohyb_streak = 0

            if pohyb_streak >= POHYB_POCET:
                locked    = True
                prev_gray = blurred.copy()
                # Najdi přesnou pozici mince v pásu
                cnts, _ = cv2.findContours(diff_th, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
                if cnts:
                    best = max(cnts, key=cv2.contourArea)
                    M = cv2.moments(best)
                    if M["m00"] != 0:
                        last_x = int(M["m10"]/M["m00"]) + wx1
                        last_y = int(M["m01"]/M["m00"]) + WAIT_BAND_TOP
                print(f"  MINCE DETEKOVÁNA: snimek {frame_idx}, "
                      f"pozice ({last_x},{last_y})")
                found_now = True

            raw_x.append(np.nan)
            raw_y.append(np.nan)

        else:
            # Sleduj minci frame diffem — POUZE POD HLADINOU
            if prev_gray is not None:
                x1 = max(0,          last_x - SEARCH_R)
                x2 = min(w,          last_x + SEARCH_R)
                y1 = max(zavora_top, last_y - 15)
                y2 = min(h,          last_y + SEARCH_R * 2)

                roi_cur  = blurred[y1:y2, x1:x2]
                roi_prev = prev_gray[y1:y2, x1:x2]

                if roi_cur.size > 0 and roi_prev.size > 0:
                    diff = cv2.absdiff(roi_cur, roi_prev)
                    _, diff_th = cv2.threshold(diff, 10, 255, cv2.THRESH_BINARY)
                    diff_th = cv2.dilate(diff_th, kernel, iterations=2)

                    cnts, _ = cv2.findContours(
                        diff_th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                    best_area = 0
                    best_cx, best_cy = None, None
                    for cnt in cnts:
                        area = cv2.contourArea(cnt)
                        if area > 15:
                            M = cv2.moments(cnt)
                            if M["m00"] != 0:
                                cx = int(M["m10"]/M["m00"]) + x1
                                cy = int(M["m01"]/M["m00"]) + y1
                                if area > best_area:
                                    best_area = area
                                    best_cx, best_cy = cx, cy

                    if best_cx is not None:
                        dist     = np.hypot(best_cx - last_x, best_cy - last_y)
                        jde_dolu = best_cy >= last_y - 15
                        if dist < MAX_SKOK and jde_dolu:
                            last_x, last_y = best_cx, best_cy
                            found_now = True

            prev_gray = blurred.copy()

            if found_now:
                raw_x.append(float(last_x - center_x))
                raw_y.append(float(last_y))
            else:
                raw_x.append(np.nan)
                raw_y.append(np.nan)

    cap.release()

    while raw_x and np.isnan(raw_x[-1]):
        raw_x.pop(); raw_y.pop()

    if len(raw_x) < 5 or np.sum(~np.isnan(np.array(raw_x))) < 5:
        print("  Mince nenalezena.")
        return None, None

    rx = np.array(raw_x, dtype=np.float64)
    ry = np.array(raw_y, dtype=np.float64)
    n_det = int(np.sum(~np.isnan(rx)))
    print(f"  Auto-track: {len(rx)} sn., {n_det} det. ({n_det/len(rx)*100:.0f}%)")
    return rx, ry

# =========================================================
# REVIZE AUTO-TRACKINGU (Video + Graf)
# =========================================================

def zkontroluj_auto_track(video_path, rx, ry, rotace, nazev_kamery):
    nazev_okna = f"REVIZE AUTO-TRACK | {nazev_kamery}"
    
    while True:
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        pts_valid = []
        
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            frame = aplikuj_rotaci(frame, rotace)
            h, w = frame.shape[:2]
            center_x = w // 2
            scale = min(SIRKA_OKNA / w, (VYSKA_OKNA - 100) / h)
            frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            
            if frame_idx < len(rx) and not np.isnan(rx[frame_idx]):
                cx = int(rx[frame_idx] + center_x)
                cy = int(ry[frame_idx])
                pts_valid.append((cx, cy))
                
            dbg = frame.copy()
            for i in range(1, len(pts_valid)):
                cv2.line(dbg, pts_valid[i-1], pts_valid[i], (0, 0, 255), 2)
            if pts_valid:
                cv2.circle(dbg, pts_valid[-1], 6, (0, 255, 0), -1)
                
            # Světlé UI pro revizi
            cv2.rectangle(dbg, (0, h-40), (w, h), (255,255,255), -1)
            cv2.putText(dbg, "AUTO-TRACKING REVIZE | Sleduj video, pote rozhodni v terminalu", 
                        (10, h-12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

            small = cv2.resize(dbg, (int(w*scale), int(h*scale)))
            cv2.imshow(nazev_okna, small)
            if cv2.waitKey(30) == 27: break

        cap.release()
        
        # Temp graf - Světlé téma
        fig, ax = plt.subplots(figsize=(4, 6), facecolor='white')
        _style_ax(ax)
        valid_x = rx[~np.isnan(rx)]
        valid_y = ry[~np.isnan(ry)]
        ax.plot(valid_x, valid_y, color='blue', marker='o', markersize=3)
        ax.invert_yaxis()
        ax.set_title("Nalezená Trajektorie", color='black')
        plt.show(block=False)
        plt.pause(0.1)

        print(f"\n==============================================")
        print(f" REVIZE: {nazev_kamery}")
        print(f"==============================================")
        
        # TADY JE TA ZMĚNA: Přidána volba [o] pro Editor
        odpoved = input(" [ENTER] = Ulozit (OK)\n [o] = Opravit spatne body (Editor)\n [r] = Smazat a naklikat cele rucne\n [p] = Prehrat znovu\n Volba: ").strip().lower()

        plt.close(fig)

        if odpoved == 'r':
            cv2.destroyWindow(nazev_okna)
            return "rucni"
        elif odpoved == 'o':
            cv2.destroyWindow(nazev_okna)
            return "oprava"
        elif odpoved == 'p':
            continue
        else:
            cv2.destroyWindow(nazev_okna)
            return "ok"


# =========================================================
# EDITOR A RUČNÍ TRACKING
# =========================================================

def rucni_track(video_path, nazev_kamery, cache_key, auto_x=None, auto_y=None):
    cache = nacti_cache()
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rotace = ziskej_rotaci(video_path)
    
    raw_x = [np.nan] * total
    raw_y = [np.nan] * total
    
    # Pokud přišla data z automatu k opravě, načteme je
    if auto_x is not None and auto_y is not None:
        for i in range(min(total, len(auto_x))):
            raw_x[i] = auto_x[i]
            raw_y[i] = auto_y[i]
            
    idx = 0
    click_pos = [None]
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, frame = cap.read()
    frame = aplikuj_rotaci(frame, rotace)
    h, w = frame.shape[:2]
    scale = min(SIRKA_OKNA / w, (VYSKA_OKNA - 50) / h)
    center_x = w // 2

    nazev_okna = f"EDITOR | {nazev_kamery} | {os.path.basename(video_path)}"
    cv2.namedWindow(nazev_okna, cv2.WINDOW_AUTOSIZE)

    def on_click(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN:
            click_pos[0] = (int(x / scale), int(y / scale))
    cv2.setMouseCallback(nazev_okna, on_click)

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret: 
            if idx >= total - 1: pass
            else: break
        frame = aplikuj_rotaci(frame, rotace)
        click_pos[0] = None
        dbg = frame.copy()
        
        # Světlé UI Editoru
        cv2.rectangle(dbg, (0, h-90), (w, h), (255,255,255), -1)
        cv2.putText(dbg, f"{nazev_kamery}  |  Snimek {idx+1}/{total}", (10, h-68), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,0), 2)
        cv2.putText(dbg, "A=vzad  D=vpred  |  KLIK=opravit bod  |  MEZERNIK=smazat bod  |  ENTER=ulozit", (10, h-38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50,50,50), 1)

        last_valid = None
        for i in range(total):
            if not np.isnan(raw_x[i]):
                px = int(raw_x[i] + center_x)
                py = int(raw_y[i])
                if last_valid is not None:
                    cv2.line(dbg, last_valid, (px, py), (0, 200, 100), 2)
                last_valid = (px, py)
                # Tady je ten ČERVENÝ KROUŽEK na aktuálním snímku
                if i == idx: cv2.circle(dbg, (px, py), 10, (0, 0, 255), 3) 
                else: cv2.circle(dbg, (px, py), 4, (0, 255, 0), -1)

        small = cv2.resize(dbg, (int(w*scale), int(h*scale)))
        cv2.imshow(nazev_okna, small)

        key = None
        while key is None and click_pos[0] is None:
            k = cv2.waitKey(30) & 0xFF
            if k != 0xFF: key = k

        if click_pos[0] is not None:
            cx, cy = click_pos[0]
            raw_x[idx] = float(cx - center_x)
            raw_y[idx] = float(cy)
            idx = min(idx + 1, total - 1)
        elif key == ord('a') or key == 81: idx = max(idx - 1, 0) # Posun zpět (A)
        elif key == ord('d') or key == 83: idx = min(idx + 1, total - 1) # Posun vpřed (D)
        elif key == ord(' '): # Vymazání bodu
            raw_x[idx] = np.nan
            raw_y[idx] = np.nan
            idx = min(idx + 1, total - 1)
        elif key == 13: # Enter = hotovo
            break
        elif key == ord('q'):
            cap.release(); cv2.destroyWindow(nazev_okna)
            return None, None

    cap.release(); cv2.destroyWindow(nazev_okna)
    
    last_valid_idx = -1
    for i in range(total-1, -1, -1):
        if not np.isnan(raw_x[i]): last_valid_idx = i; break
    if last_valid_idx == -1: return None, None
        
    rx = np.array(raw_x[:last_valid_idx+1], dtype=np.float64)
    ry = np.array(raw_y[:last_valid_idx+1], dtype=np.float64)

    cache[cache_key] = (rx.tolist(), ry.tolist())
    uloz_cache(cache)
    print(f"    [{nazev_kamery}] ULOZENO.")
    return rx, ry


# =========================================================
# HYBRIDNÍ ROZHODOVAČ (Auto -> Zkontrolovat -> Ručně)
# =========================================================

def vyres_tracking(video_path, nazev_kamery, cache_key):
    cache = nacti_cache()
    if cache_key in cache:
        print(f"    [{nazev_kamery}] Nacteno z cache ({len(cache[cache_key][0])} sn.)")
        rx_raw, ry_raw = cache[cache_key]
        rx = np.array([float('nan') if v is None else float(v) for v in rx_raw])
        ry = np.array([float('nan') if v is None else float(v) for v in ry_raw])
        return rx, ry
        
    rotace = ziskej_rotaci(video_path)
    print(f"\n---> Spoustim AUTO-TRACKING pro {nazev_kamery}")
    rx, ry = automaticky_track(video_path, rotace, nazev_kamery)

    if rx is not None:
        stav = zkontroluj_auto_track(video_path, rx, ry, rotace, nazev_kamery)
        if stav == "ok":
            cache[cache_key] = (rx.tolist(), ry.tolist())
            uloz_cache(cache)
            print(f"    [{nazev_kamery}] AUTO-TRACKING Ulozen.")
            return rx, ry
        elif stav == "oprava":
            print(f"---> Spoustim EDITOR (Oprava chyb) pro {nazev_kamery}")
            # Tady posíláme nalezená data do Editoru k oprave!
            return rucni_track(video_path, nazev_kamery, cache_key, auto_x=rx, auto_y=ry)
        else:
            print(f"---> Spoustim RUCNI TRACKING (Cisty stit) pro {nazev_kamery}")
            return rucni_track(video_path, nazev_kamery, cache_key)
    else:
        print(f"    [{nazev_kamery}] Auto-tracking nenasel minci.")
        print(f"---> Spoustim RUCNI TRACKING pro {nazev_kamery}")
        return rucni_track(video_path, nazev_kamery, cache_key)
    

# =========================================================
# ZPRACOVÁNÍ DAT (Kalibrace, Čištění, Grafy)
# =========================================================

# Nahraď funkci cistuj_a_kalibruj tímto:

def cistuj_a_kalibruj(raw_x, raw_y, mpx_x, mpx_y):
    valid = np.where(~np.isnan(raw_x))[0]
    if len(valid) < 5: return None, None, None
    si = valid[0]; ei = valid[-1]
    
    tx = raw_x[si:ei+1].copy()
    ty = raw_y[si:ei+1].copy()
    
    mask = np.isnan(tx)
    idx  = np.arange(len(tx))
    if mask.any() and (~mask).sum() >= 2:
        tx[mask] = np.interp(idx[mask], idx[~mask], tx[~mask])
        ty[mask] = np.interp(idx[mask], idx[~mask], ty[~mask])

    # Detekce stabilního pádu
    start = 0
    for i in range(len(ty) - 2):
        if (ty[i+1] - ty[i]) >= 3 and (ty[i+2] - ty[i+1]) >= 3:
            start = i
            break

    # Zásadní úprava: Zapamatujeme si ABSOLUTNÍ číslo snímku z původního videa
    abs_start_frame = si + start

    tx = tx[start:]
    ty = ty[start:]

    x_cm = (tx - tx[0]) * mpx_x * 100
    y_cm = (ty - ty[0]) * mpx_y * 100
    y_cm = np.clip(y_cm, 0, None)
    
    # Vracíme 3 hodnoty! Přidán startovní snímek.
    return x_cm, y_cm, abs_start_frame

def pridej_zacatek(x_cm, y_cm, z_cm, time_s):
    # Škálování podle hloubky akvária zůstává
    if y_cm[-1] > 1.0:
        scale = HLOUBKA_AKVARIA_CM / y_cm[-1]
        y_cm  = y_cm * scale
        
    # OPRAVA: Odstraněn pokus o vkládání bodů [0.0, 1.0] atd.
    # Data prostě pošleme dál tak, jak jsou, protože už bezpečně 
    # začínají na (0,0,0) díky předchozí funkci.
    
    # Jen srovnáme čas, aby začínal přesně na nule
    t_out = time_s - time_s[0]
    
    return x_cm, y_cm, z_cm, t_out

def zpracuj_par(video1_path, video2_path, hmotnost_kg):
    nazev = os.path.splitext(os.path.basename(video1_path))[0]
    print(f"\n==============================================")
    print(f" ZPRACOVAVAM PAR: {nazev}")
    print(f"==============================================")

    key1 = f"{nazev}_cam1"
    raw1x, raw1y = vyres_tracking(video1_path, "Kamera 1 (predni)", key1)
    if raw1x is None: return None
    
    # Rozbalujeme 3 hodnoty
    x_cm, y1_cm, start1 = cistuj_a_kalibruj(raw1x, raw1y, CAM1_MPX_X, CAM1_MPX_Y)
    if x_cm is None: return None
    
    key2 = f"{nazev}_cam2"
    raw2x, raw2y = vyres_tracking(video2_path, "Kamera 2 (bocni)", key2)
    
    if raw2x is None:
        z_cm = np.zeros_like(x_cm)
        y_cm = y1_cm
        time_s = np.arange(len(x_cm)) / FPS_VIDEA
    else:
        # Rozbalujeme 3 hodnoty
        z_raw, y2_cm, start2 = cistuj_a_kalibruj(raw2x, raw2y, CAM2_MPX_X, CAM2_MPX_Y)
        if z_raw is None:
            z_cm = np.zeros_like(x_cm)
            y_cm = y1_cm
            time_s = np.arange(len(x_cm)) / FPS_VIDEA
        else:
            # TADY JE TA MAGIE: Synchronizace podle absolutního čísla snímku z videí
            t1 = (np.arange(len(x_cm)) + start1) / FPS_VIDEA
            t2 = (np.arange(len(z_raw)) + start2) / FPS_VIDEA

            # Společný čas začíná až tam, kde OBĚ kamery už stoprocentně vidí padající minci
            t_start = max(t1[0], t2[0])
            t_end   = min(t1[-1], t2[-1])
            
            if t_end <= t_start: return None # Bezpečnostní pojistka

            n = max(int((t_end - t_start) * FPS_VIDEA), 5)
            t_sp = np.linspace(t_start, t_end, n)

            # Sjednotíme data na společnou časovou osu
            x_cm = interp1d(t1, x_cm, kind='linear')(t_sp)
            y_cm = interp1d(t1, y1_cm, kind='linear')(t_sp)
            z_cm = interp1d(t2, z_raw, kind='linear')(t_sp)

            # Teprve TEĎ posuneme starty os na [0, 0, 0] — nyní jsou data v čase perfektně sladěna!
            x_cm = x_cm - x_cm[0]
            y_cm = y_cm - y_cm[0]
            z_cm = z_cm - z_cm[0]
            
            time_s = t_sp - t_sp[0]

    y_cm = np.clip(y_cm, 0, HLOUBKA_AKVARIA_CM)
    x_cm, y_cm, z_cm, time_s = pridej_zacatek(x_cm, y_cm, z_cm, time_s)

    return {
        "nazev":       nazev,
        "x_cm":        x_cm,
        "y_cm":        y_cm,
        "z_cm":        z_cm,
        "time_s":      time_s,
        "final_x":     x_cm[-1],
        "final_z":     z_cm[-1],
        "hmotnost_kg": hmotnost_kg,
        "kvalita":     1.0,
    }

def aplikuj_skalovacie_omezeni(vsechna_data, max_x_cm=31.0, max_z_cm=37.0):
    """
    Škáluje všechny trajektorie stejným koeficientem tak, aby žádný dopad 
    nepřesahoval max_x_cm (V-Z) a max_z_cm (S-J).
    """
    # Najdi maximální rozměry dopadů
    final_xs = np.array([d["final_x"] for d in vsechna_data])
    final_zs = np.array([d["final_z"] for d in vsechna_data])
    
    max_dopad_x = max(abs(final_xs.min()), abs(final_xs.max()))
    max_dopad_z = max(abs(final_zs.min()), abs(final_zs.max()))
    
    # Vypočti škálovací koeficient (vezmi ten přísnější)
    koef_x = max_x_cm / (2 * max_dopad_x) if max_dopad_x > 0 else 1.0
    koef_z = max_z_cm / (2 * max_dopad_z) if max_dopad_z > 0 else 1.0
    koef = min(koef_x, koef_z, 1.0)  # Nikdy nezvětšuj, jen zmenšuj
    
    if koef < 1.0:
        print(f"\n  ŠKÁLOVÁNÍ: Dopady přesahují limit → aplikuji koeficient {koef:.3f}")
        print(f"    Původní rozsah: X ±{max_dopad_x:.1f} cm, Z ±{max_dopad_z:.1f} cm")
        print(f"    Nový rozsah:    X ±{max_dopad_x*koef:.1f} cm, Z ±{max_dopad_z*koef:.1f} cm")
        
        for d in vsechna_data:
            d["x_cm"] = d["x_cm"] * koef
            d["z_cm"] = d["z_cm"] * koef
            d["final_x"] = d["final_x"] * koef
            d["final_z"] = d["final_z"] * koef
    else:
        print(f"\n  ŠKÁLOVÁNÍ: Dopady v limitu, škálování není potřeba.")
    
    return vsechna_data

def sparuj_videa():
    videa1 = sorted(glob.glob(os.path.join(CAM1_SLOZKA, "*.mp4")))
    videa2 = sorted(glob.glob(os.path.join(CAM2_SLOZKA, "*.mp4")))
    if not videa1: print(f"CHYBA: Žádná videa v '{CAM1_SLOZKA}'"); return []
    if not videa2: print(f"CHYBA: Žádná videa v '{CAM2_SLOZKA}'"); return []

    def cislo_padu(path, cam):
        name = os.path.splitext(os.path.basename(path))[0]
        m = re.search(rf'{cam}(\d+)$', name)
        return m.group(1) if m else None

    idx2 = {}
    for p in videa2:
        k = cislo_padu(p, '2')
        if k: idx2[k] = p

    pary = []; nespárovane = []
    for v1 in videa1:
        k = cislo_padu(v1, '1')
        if k and k in idx2: pary.append((v1, idx2[k]))
        else: nespárovane.append(v1)

    if nespárovane:
        sparovane2 = {v2 for _,v2 in pary}
        volne2 = sorted(v for v in videa2 if v not in sparovane2)
        for v1,v2 in zip(sorted(nespárovane), volne2):
            print(f"  [~] Záložní párování: {os.path.basename(v1)} <-> {os.path.basename(v2)}")
            pary.append((v1,v2))
    return pary

def pary_z_cache():
    """Páry pádů přímo z cache — umožní přegenerovat grafy i bez videí."""
    cache = nacti_cache()
    nazvy = sorted(k[:-len("_cam1")] for k in cache
                   if k.endswith("_cam1") and k[:-len("_cam1")] + "_cam2" in cache)
    # zpracuj_par bere název pádu z cesty k videu kamery 1
    return [(n + ".mp4", n + ".mp4") for n in nazvy]

def prumeruj(vsechna_data):
    d_ref = max(vsechna_data, key=lambda d: len(d["time_s"]))
    t_sp  = d_ref["time_s"]
    N     = len(t_sp)
    xs, ys, zs, vxs, vys, vzs, Eps, Eks, Ezs = ([] for _ in range(9))

    def derivace_silna(arr, time_s):
        n = len(arr)
        win = min(15, n if n % 2 == 1 else n - 1)
        if win < 5:
            return np.diff(arr) / np.diff(time_s)
        arr_clean = arr.copy()
        nan_mask = np.isnan(arr_clean)
        if nan_mask.any():
            idx = np.arange(len(arr_clean))
            if (~nan_mask).sum() >= 2:
                arr_clean[nan_mask] = np.interp(
                    idx[nan_mask], idx[~nan_mask], arr_clean[~nan_mask])
            else:
                arr_clean = np.nan_to_num(arr_clean, nan=0.0)
        arr_smooth = savgol_filter(arr_clean, window_length=win, polyorder=3)
        dt = np.diff(time_s)
        v  = np.diff(arr_smooth) / dt
        mu, sigma = np.mean(v), np.std(v)
        if sigma > 0:
            mask = np.abs(v - mu) > 2 * sigma
            if mask.any() and (~mask).sum() >= 2:
                v[mask] = np.interp(
                    np.where(mask)[0], np.where(~mask)[0], v[~mask])
        return v

    for d in vsechna_data:
        t  = d["time_s"]
        xi = interp1d(t, d["x_cm"], kind='linear',
                      fill_value=(d["x_cm"][0], d["x_cm"][-1]),
                      bounds_error=False)(t_sp)
        yi = interp1d(t, d["y_cm"], kind='linear',
                      fill_value=(d["y_cm"][0], d["y_cm"][-1]),
                      bounds_error=False)(t_sp)
        zi = interp1d(t, d["z_cm"], kind='linear',
                      fill_value=(d["z_cm"][0], d["z_cm"][-1]),
                      bounds_error=False)(t_sp)
        xs.append(xi); ys.append(yi); zs.append(zi)

        vx = derivace_silna(xi, t_sp)
        vy = derivace_silna(yi, t_sp)
        vz = derivace_silna(zi, t_sp)
        vxs.append(vx); vys.append(vy); vzs.append(vz)

        m     = d["hmotnost_kg"]
        h_max = yi[-1] / 100.0           # [m]
        # KLÍČOVÉ: Ep musí mít délku N-1 (stejnou jako t_v)
        # yi[:-1] = všechny body kromě posledního
        h_nad = h_max - yi[:-1] / 100.0  # [m], délka N-1

        Ep = m * G * h_nad                # [J], délka N-1
        Ek = 0.5 * m * ((vx/100)**2 + (vy/100)**2 + (vz/100)**2)  # [J], délka N-1
        El = np.clip(m * G * h_max - Ep - Ek, 0, None)

        Eps.append(Ep); Eks.append(Ek); Ezs.append(El)

    def st(a):
        # Ořež všechny pole na nejkratší délku před průměrováním
        min_len = min(len(x) for x in a)
        arr = np.array([x[:min_len] for x in a])
        return arr.mean(0), arr.std(0)

    t_v = (t_sp[:-1] + t_sp[1:]) / 2  # délka N-1

    return {
        "t": t_sp, "t_v": t_v, "n": len(vsechna_data),
        "hmotnost_kg": vsechna_data[0]["hmotnost_kg"],
        "x": st(xs), "y": st(ys), "z": st(zs),
        "vx": st(vxs), "vy": st(vys), "vz": st(vzs),
        "Ep": st(Eps), "Ek": st(Eks), "Ez": st(Ezs),
        "final_x_vals": np.array([d["final_x"] for d in vsechna_data]),
        "final_z_vals": np.array([d["final_z"] for d in vsechna_data]),
        "vsechna_data": vsechna_data,
    }
def uloz_vsechny_xy(pr, label):
    vsechna = pr["vsechna_data"]; ym, ys = pr["y"]; n = pr["n"]

    def sys_chyba(y_arr):
        return np.sqrt(0.6**2 + 0.2**2 + (0.025 * y_arr)**2)

    fig, ax = plt.subplots(figsize=(11, 11), facecolor='white')
    _style_ax(ax)
    barvy = plt.cm.tab20(np.linspace(0, 1, len(vsechna)))

    for i, d in enumerate(vsechna):
        xd = np.array(d["x_cm"])
        yd = np.array(d["y_cm"])
        col = barvy[i]
        err_x = sys_chyba(yd)
        ax.fill_betweenx(yd, xd - err_x, xd + err_x, color=col, alpha=0.12)
        ax.plot(xd, yd, color=col, lw=1.2, alpha=0.8, label=d["nazev"])
        ax.scatter(xd[0],  yd[0],  color=col, s=35, zorder=4, marker='o')
        ax.scatter(xd[-1], yd[-1], color=col, s=35, zorder=4, marker='X')

    xm, xs = pr["x"]
    ax.fill_betweenx(ym, xm - xs, xm + xs, color='#cc2222', alpha=0.25, zorder=4)
    ax.plot(xm, ym, color='#cc2222', lw=3.0, ls='--', zorder=5)

    ax.invert_yaxis()
    ax.set_xlabel('Forward drift X [cm]', fontsize=12, color='black')
    ax.set_ylabel('Depth Y [cm]', fontsize=12, color='black')
    ax.set_title(f'ALL TRAJECTORIES X–Y: {label.upper()}  (n={n})',
                 fontsize=13, fontweight='bold', color='black', pad=12)
    ax.axvline(0, color='black', lw=0.8, ls=':', alpha=0.4)

    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D

    traj_handles, traj_labels = ax.get_legend_handles_labels()
    leg1 = ax.legend(handles=traj_handles, labels=traj_labels,
                     facecolor='white', edgecolor='#ccc', labelcolor='black',
                     fontsize=7, ncol=1,
                     bbox_to_anchor=(1.01, 1), loc='upper left',
                     borderaxespad=0)
    ax.add_artist(leg1)

    vysvetlivky = [
        Line2D([0], [0], color='#cc2222', lw=3, ls='--', label='Mean trajectory'),
        Patch(facecolor='#cc2222', alpha=0.25, label='±1σ (variability between drops)'),
        Patch(facecolor='gray',    alpha=0.20, label='Measurement error (calib.+warp)'),
    ]
    ax.legend(handles=vysvetlivky, facecolor='white', edgecolor='#ccc',
              labelcolor='black', fontsize=8, loc='upper left')

    plt.tight_layout()
    plt.savefig(f"TRACKING_vsechny_XY_{label}.png", dpi=300, bbox_inches='tight')
    plt.close(fig)
    print("  -> All X-Y trajectories saved.")

def uloz_trajektorie(pr, label):
    ym, ys = pr["y"]; t = pr["t"]; n = pr["n"]
    vsechna = pr["vsechna_data"]
    barvy = plt.cm.tab20(np.linspace(0, 1, len(vsechna)))
    fig, axes = plt.subplots(1, 3, figsize=(16, 6), facecolor='white')
    fig.suptitle(f'TRAJEKTORIE: {label.upper()}  (n={n})',
                 fontsize=14, fontweight='bold', color='black')
    ax = axes[0]; _style_ax(ax)
    ax.fill_between(t, ym-ys, ym+ys, color='#00d4d4', alpha=0.25, label=f'±1σ')
    ax.plot(t, ym, color='#00d4d4', lw=2.5, label='Průměr Y')
    ax.invert_yaxis()
    ax.set_xlabel('Čas [s]', color='black', fontsize=11)
    ax.set_ylabel('Hloubka y [cm]', color='black', fontsize=11)
    ax.set_title('Hloubka Y(t)', color='black', fontsize=11)
    ax.legend(facecolor='white', edgecolor='#ccc', labelcolor='black', fontsize=9)
    ax2 = axes[1]; _style_ax(ax2)
    for i, d in enumerate(vsechna):
        ax2.plot(d["time_s"], d["x_cm"], color=barvy[i], lw=1.2, alpha=0.7, label=d["nazev"])
    ax2.axhline(0, color='black', lw=0.8, ls='--', alpha=0.4)
    ax2.set_title('Přední drift X(t)', color='black', fontsize=11)
    ax2.set_xlabel('Čas [s]', color='black', fontsize=11)
    ax2.set_ylabel('X [cm]', color='black', fontsize=11)
    ax2.legend(facecolor='white', edgecolor='#ccc', labelcolor='black', fontsize=7, ncol=2)
    ax3 = axes[2]; _style_ax(ax3)
    for i, d in enumerate(vsechna):
        ax3.plot(d["time_s"], d["z_cm"], color=barvy[i], lw=1.2, alpha=0.7, label=d["nazev"])
    ax3.axhline(0, color='black', lw=0.8, ls='--', alpha=0.4)
    ax3.set_title('Boční drift Z(t)', color='black', fontsize=11)
    ax3.set_xlabel('Čas [s]', color='black', fontsize=11)
    ax3.set_ylabel('Z [cm]', color='black', fontsize=11)
    ax3.legend(facecolor='white', edgecolor='#ccc', labelcolor='black', fontsize=7, ncol=2)
    plt.tight_layout()
    plt.savefig(f"TRACKING_trajektorie_{label}.png", dpi=300, bbox_inches='tight')
    plt.close(fig)
    print("  -> Trajektorie uloženy.")



def uloz_2d_projekce(pr, label):
    xm, xs = pr["x"]; ym, ys = pr["y"]; zm, zs = pr["z"]; n = pr["n"]
    vsechna = pr["vsechna_data"]
    barvy = plt.cm.tab20(np.linspace(0, 1, len(vsechna)))

    fig, axes = plt.subplots(1, 3, figsize=(18, 7), facecolor='white')
    fig.suptitle(f'2D PROJECTIONS: {label.upper()}  (n={n})',
                 fontsize=13, fontweight='bold', color='black')

    configs = [
        (axes[0], 'x_cm', 'y_cm', 'Forward drift X [cm]', 'Depth Y [cm]',
         'Front view (X–Y)', '#00d4d4', True,  xm, xs, ym, ys),
        (axes[1], 'z_cm', 'y_cm', 'Side drift Z [cm]',    'Depth Y [cm]',
         'Side view (Z–Y)',  '#ff9900', True,  zm, zs, ym, ys),
        (axes[2], 'x_cm', 'z_cm', 'Forward drift X [cm]', 'Side drift Z [cm]',
         'Top view (X–Z)',   '#cc88ff', False, xm, xs, zm, zs),
    ]

    for ax, xkey, ykey, xl, yl, tit, col, inv, am, ae, bm, be in configs:
        _style_ax(ax)

        # Individuální trajektorie
        for i, d in enumerate(vsechna):
            ax.plot(d[xkey], d[ykey],
                    color=barvy[i], lw=0.9, alpha=0.35)

        # Průměr + ±1σ
        ax.fill_between(am, bm - be, bm + be,
                        color=col, alpha=0.30, label='±1σ')
        ax.plot(am, bm, color=col, lw=2.5, label='Mean')
        ax.scatter(am[0],  bm[0],  color='#00cc66', s=80, zorder=6)
        ax.scatter(am[-1], bm[-1], color='#ff4444', s=80, zorder=6, marker='X')

        ax.set_xlabel(xl, color='black', fontsize=10)
        ax.set_ylabel(yl, color='black', fontsize=10)
        ax.set_title(tit, color='black', fontsize=11)
        if inv: ax.invert_yaxis()
        ax.legend(facecolor='white', edgecolor='#ccc',
                  labelcolor='black', fontsize=8)

    plt.tight_layout()
    plt.savefig(f"TRACKING_2D_projekce_{label}.png", dpi=300, bbox_inches='tight')
    plt.close(fig)
    print("  -> 2D projections saved.")


def uloz_dopadova_ruzice(pr, label):
    fx = pr["final_x_vals"]; fz = pr["final_z_vals"]; n = pr["n"]
    mx, mz = fx.mean(), fz.mean(); sx, sz = fx.std(), fz.std()

    fig, ax = plt.subplots(figsize=(8, 8), facecolor='white')
    _style_ax(ax)

    for mult, alpha in [(2, 0.08), (1, 0.20)]:
        theta = np.linspace(0, 2*np.pi, 200)
        ax.fill(mx + mult*sx*np.cos(theta), mz + mult*sz*np.sin(theta),
                color='#00d4d4', alpha=alpha, label=f'±{mult}σ')
        ax.plot(mx + mult*sx*np.cos(theta), mz + mult*sz*np.sin(theta),
                color='#00d4d4', lw=1, ls='--', alpha=0.6)

    colors = plt.cm.coolwarm(np.linspace(0, 1, n))
    for i, (x, z) in enumerate(zip(fx, fz)):
        ax.scatter(x, z, color=colors[i], s=150, zorder=5,
                   edgecolors='black', lw=1.2)
        ax.text(x, z, f'  {i+1}', color='black', fontsize=8, va='center')

    ax.scatter(mx, mz, color='#00ff88', s=200, zorder=6,
               marker='+', linewidths=3,
               label=f'Mean ({mx:.1f}, {mz:.1f}) cm')
    ax.axhline(0, color='black', lw=0.8, ls=':', alpha=0.4)
    ax.axvline(0, color='black', lw=0.8, ls=':', alpha=0.4)
    ax.set_xlabel('X [cm]', fontsize=12, color='black')
    ax.set_ylabel('Z [cm]', fontsize=12, color='black')
    ax.set_title(f'LANDING SCATTER: {label.upper()}',
                 fontsize=13, fontweight='bold', color='black', pad=15)
    ax.set_aspect('equal')

    all_x = np.concatenate([fx, [mx - 2*sx, mx + 2*sx]])
    all_z = np.concatenate([fz, [mz - 2*sz, mz + 2*sz]])
    r = max(max(abs(all_x.min()), abs(all_x.max())) * 1.3,
            max(abs(all_z.min()), abs(all_z.max())) * 1.3,
            3.0)
    ax.set_xlim(-r, r); ax.set_ylim(-r, r)

    ax.text(0.02, 0.97, f'n={n}\nσX={sx:.2f} cm\nσZ={sz:.2f} cm',
            transform=ax.transAxes, color='black', fontsize=10, va='top',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='#ccc'))
    ax.legend(facecolor='white', edgecolor='#ccc', labelcolor='black', fontsize=9)
    plt.tight_layout()
    plt.savefig(f"TRACKING_dopadova_ruzice_{label}.png", dpi=300)
    plt.close(fig)
    print("  -> Landing scatter saved.")


def uloz_energie(pr, label):
    t_v = pr["t_v"]; n = pr["n"]; m = pr["hmotnost_kg"]
    Epm, Eps_ = pr["Ep"]
    Ekm, Eks_ = pr["Ek"]
    Ezm, Ezs_ = pr["Ez"]

    Ep_max_teor = m * G * (HLOUBKA_AKVARIA_CM / 100) * 1000  # mJ

    h_max_cm = HLOUBKA_AKVARIA_CM
    dh_cm    = np.sqrt(0.6**2 + 0.2**2 + (0.025 * h_max_cm)**2)
    dEp_sys  = m * G * (dh_cm / 100) * 1000
    dEk_sys  = np.maximum(0.25 * np.abs(Ekm) * 1000, 0.05)
    dEz_sys  = np.sqrt(dEp_sys**2 + dEk_sys**2)

    fig, ax = plt.subplots(figsize=(10, 6), facecolor='white')
    _style_ax(ax)

    ep_err = np.sqrt((Eps_ * 1000)**2 + dEp_sys**2)
    ax.fill_between(t_v, np.maximum(0, Epm*1000 - ep_err), Epm*1000 + ep_err,
                    color='#ff9900', alpha=0.2)
    ax.plot(t_v, Epm*1000, color='#ff9900', lw=2.5,
            label='Ep — potential energy [mJ]')

    ek_err = np.sqrt((Eks_ * 1000)**2 + dEk_sys**2)
    ax.fill_between(t_v, np.maximum(0, Ekm*1000 - ek_err), Ekm*1000 + ek_err,
                    color='#00d4d4', alpha=0.2)
    ax.plot(t_v, Ekm*1000, color='#00d4d4', lw=2.5,
            label='Ek — kinetic energy [mJ]')

    ez_err = np.sqrt((Ezs_ * 1000)**2 + dEz_sys**2)
    ax.fill_between(t_v, np.maximum(0, Ezm*1000 - ez_err), Ezm*1000 + ez_err,
                    color='#d45555', alpha=0.15)
    ax.plot(t_v, Ezm*1000, color='#d45555', lw=2, ls='--',
            label='El — dissipated to heat [mJ]')

    ax.axhline(Ep_max_teor, color='gray', lw=1, ls=':', alpha=0.6,
               label=f'Ep₀ theoretical = {Ep_max_teor:.1f} mJ')

    total   = float(Ezm[-1] * 1000)
    total_s = float(np.sqrt((Ezs_[-1]*1000)**2 + dEz_sys[-1]**2))
    ax.text(0.98, 0.97,
            f'Mass: {m*1000:.1f} g  |  n = {n}\n'
            f'Ep₀ = mgh = {Ep_max_teor:.1f} mJ\n'
            f'Total dissipation: {total:.1f} ± {total_s:.1f} mJ\n'
            f'Error: stat. ⊕ calib. ⊕ warp',
            transform=ax.transAxes, color='black', fontsize=9,
            va='top', ha='right',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='#ccc'))

    ax.set_title(f'ENERGY ANALYSIS: {label.upper()}',
                 fontsize=14, fontweight='bold', color='black', pad=15)
    ax.set_xlabel('Time [s]', fontsize=12, color='black')
    ax.set_ylabel('Energy [mJ]', fontsize=12, color='black')
    ax.set_ylim(bottom=0)
    ax.legend(facecolor='white', edgecolor='#ccc', labelcolor='black', fontsize=10)
    plt.tight_layout()
    plt.savefig(f"TRACKING_energie_{label}.png", dpi=300)
    plt.close(fig)
    print("  -> Energy plot saved.")

def uloz_csv(vsechna_data, pr, label):
    t=pr["t"]; xm,xs=pr["x"]; ym,ys=pr["y"]; zm,zs=pr["z"]
    with open(f"TRACKING_data_{label}.csv",'w',newline='',encoding='utf-8') as f:
        w=csv.writer(f)
        w.writerow([f"# HYBRID TRACKING — {label.upper()}"])
        w.writerow([f"# n={pr['n']} padu | FPS={FPS_VIDEA}"])
        w.writerow([])
        w.writerow(["### PRUMERNA TRAJEKTORIE ###"])
        w.writerow(["Cas_s","X_prumer_cm","X_std_cm","Y_prumer_cm","Y_std_cm","Z_prumer_cm","Z_std_cm"])
        for i in range(len(t)):
            w.writerow([round(t[i],4),round(xm[i],3),round(xs[i],3),
                        round(ym[i],3),round(ys[i],3),round(zm[i],3),round(zs[i],3)])
        w.writerow([])
        w.writerow(["### INDIVIDUALNI DOPADY ###"])
        w.writerow(["Video","Final_X_cm","Final_Y_cm","Final_Z_cm"])
        for d in vsechna_data:
            w.writerow([d["nazev"],round(d["final_x"],3),
                        round(d["y_cm"][-1],3),round(d["final_z"],3)])
    print(f"  -> CSV uložen.")



def uloz_3d_graf(pr, label):
    xm, xs = pr["x"]; ym, ys = pr["y"]; zm, zs = pr["z"]; n = pr["n"]
    vsechna = pr["vsechna_data"]

    fig = plt.figure(figsize=(14, 10), facecolor='white')
    ax  = fig.add_subplot(111, projection='3d')
    ax.set_facecolor('white'); fig.patch.set_facecolor('white')

    barvy = plt.cm.tab20(np.linspace(0, 1, len(vsechna)))
    
    # 1. Vykreslení všech individuálních pádů
    for i, d in enumerate(vsechna):
        ax.plot(d["x_cm"], d["z_cm"], d["y_cm"],
                color=barvy[i], lw=0.8, alpha=0.35)

    # 2. Vykreslení průměrné trajektorie (tlustá červená)
    ax.plot(xm, zm, ym, color='#cc2222', lw=3, zorder=5, label='Mean')

    # SMAZÁNY TŘI ŘÁDKY VYTVÁŘEJÍCÍ FALEŠNÉ STÍNY/ČÁRY NA STĚNÁCH

    # 3. Vykreslení odchylek (kříže na červené čáře)
    step = max(1, len(xm)//10)
    for i in range(0, len(xm), step):
        ax.plot([xm[i]-xs[i], xm[i]+xs[i]], [zm[i], zm[i]], [ym[i], ym[i]],
                color='#d45555', lw=1.2, alpha=0.7)
        ax.plot([xm[i], xm[i]], [zm[i]-zs[i], zm[i]+zs[i]], [ym[i], ym[i]],
                color='#ff9900', lw=1.2, alpha=0.7)
        ax.plot([xm[i], xm[i]], [zm[i], zm[i]], [ym[i]-ys[i], ym[i]+ys[i]],
                color='#aaaaff', lw=1.2, alpha=0.7)

    # 4. Startovní a cílový bod
    ax.scatter([xm[0]], [zm[0]], [ym[0]],
               color='#00cc66', s=120, zorder=6, label='Start')
    ax.scatter([xm[-1]], [zm[-1]], [ym[-1]],
               color='#ff4444', s=120, zorder=6, marker='X', label='End')

    # 5. Nastavení grafu
    ax.invert_zaxis()
    ax.set_xlabel('X [cm]', color='black', fontsize=10)
    ax.set_ylabel('Z [cm]', color='black', fontsize=10)
    ax.set_zlabel('Y [cm]', color='black', fontsize=10)
    ax.tick_params(colors='black')
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.set_title(f'3D TRAJECTORIES: {label.upper()}  (n={n})',
                 color='black', fontsize=13, fontweight='bold', pad=15)
    ax.legend(facecolor='white', edgecolor='#ccc', labelcolor='black')

    plt.tight_layout()
    plt.savefig(f"PRUMER_3D_{label}.png", dpi=300, bbox_inches='tight')
    plt.close(fig)
    print("  -> 3D trajectories saved.")
    
# =========================================================
# SPUŠTĚNÍ
# =========================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stereo tracking padající mince (2 kamery) -> 3D trajektorie a grafy.")
    parser.add_argument("dataset",
        help="složka s podsložkami 1_kamera/ a 2_kamera/ a/nebo souborem tracking_cache.json")
    parser.add_argument("-o", "--out",
        help="kam uložit grafy a CSV (výchozí: results/<název datasetu>)")
    args = parser.parse_args()

    data_dir     = os.path.abspath(args.dataset)
    CAM1_SLOZKA  = os.path.join(data_dir, "1_kamera")
    CAM2_SLOZKA  = os.path.join(data_dir, "2_kamera")
    CACHE_SOUBOR = os.path.join(data_dir, "tracking_cache.json")
    out_dir = os.path.abspath(args.out or os.path.join(
        "results", os.path.basename(os.path.normpath(data_dir))))

    print("=" * 55)
    print("HYBRIDNÍ TRACKING MINCE (Auto + Ruční kontrola)")
    print("=" * 55)

    if glob.glob(os.path.join(CAM1_SLOZKA, "*.mp4")):
        pary = sparuj_videa()
    else:
        print("Videa nenalezena -> zpracovávám pouze data z tracking_cache.json")
        pary = pary_z_cache()
    if not pary: sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)
    os.chdir(out_dir)  # grafy a CSV se ukládají do aktuální složky
    print(f"\nNalezeno {len(pary)} párů videí.\n")

    vsechna_data = []
    for v1, v2 in pary:
        hmotnost = ziskej_hmotnost(os.path.basename(v1))
        vysledek = zpracuj_par(v1, v2 if v2 else v1, hmotnost)
        if vysledek:
            vsechna_data.append(vysledek)

    if len(vsechna_data) < 2:
        print("Málo dat (potřeba >= 2 páry).")
        sys.exit(1)

    vsechna_data = aplikuj_skalovacie_omezeni(vsechna_data, max_x_cm=31.0, max_z_cm=37.0)

    label = os.path.commonprefix([d["nazev"] for d in vsechna_data]).strip("_- ")

    if not label: label = vsechna_data[0]["nazev"]

    print(f"\n{'='*55}")
    print(f"Průměruji {len(vsechna_data)} pádů -> '{label}'")
    print("="*55)

    pr = prumeruj(vsechna_data)
    uloz_vsechny_xy(pr, label)
    uloz_trajektorie(pr, label)
    uloz_2d_projekce(pr, label)
    uloz_energie(pr, label)
    uloz_dopadova_ruzice(pr, label)
    uloz_3d_graf(pr, label)
    uloz_csv(vsechna_data, pr, label)

    print(f"\n{'='*55}")
    print("HOTOVO!")
    fx=pr["final_x_vals"]; fz=pr["final_z_vals"]
    print(f"  Dopady X: {fx.mean():.2f} ± {fx.std():.2f} cm")
    print(f"  Dopady Z: {fz.mean():.2f} ± {fz.std():.2f} cm")
    print("="*55)