import cv2
import numpy as np
import glob
import os
import subprocess
import sys

# Složky s videi
SLOZKY = ["1_kamera", "2_kamera"]

def trim_video(video_path):
    """
    Přehraje video snímek po snímku.
    MEZERNIK = další snímek
    SHIFT+MEZERNIK (nebo B) = předchozí snímek
    ENTER = ořež — smaž vše od začátku po tento snímek
    Q = přeskoč toto video beze změny
    """
    cap   = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    nazev = os.path.basename(video_path)

    nazev_okna = f"TRIM | {nazev}"
    cv2.namedWindow(nazev_okna, cv2.WINDOW_NORMAL)

    # Detekuj rotaci z metadat videa (telefony často ukládají video rotované)
    # OpenCV ignoruje EXIF rotaci — musíme ji aplikovat ručně
    rotace = None
    try:
        import subprocess, json
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", video_path],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            data = json.loads(r.stdout)
            for stream in data.get("streams", []):
                rot = stream.get("tags", {}).get("rotate", None)
                if rot:
                    rotace = int(rot)
                    break
    except Exception:
        pass

    def aplikuj_rotaci(frame, rot):
        if rot == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rot == 270 or rot == -90:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif rot == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        return frame

    idx = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, frame = cap.read()
    frame = aplikuj_rotaci(frame, rotace)
    # Po rotaci přepočítej w, h
    h, w = frame.shape[:2]
    cv2.resizeWindow(nazev_okna, int(w * 0.4), int(h * 0.8))

    while True:
        dbg = frame.copy()

        # Info overlay — dole aby nezakrýval video
        cv2.rectangle(dbg, (0, h - 80), (w, h), (0, 0, 0), -1)
        cv2.putText(dbg, f"{nazev}  |  {idx + 1}/{total}  ({idx / fps:.2f} s)",
                    (8, h - 58), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.putText(dbg, "MEZERNIK=dalsi  B=zpet  ENTER=orez  Q=preskoc",
                    (8, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        # Progress bar úplně dole
        prog = int(w * idx / max(total - 1, 1))
        cv2.rectangle(dbg, (0, h - 8), (w, h), (50, 50, 50), -1)
        cv2.rectangle(dbg, (0, h - 8), (prog, h), (0, 200, 100), -1)

        cv2.imshow(nazev_okna, dbg)
        key = cv2.waitKey(0)

        if key == ord(' '):          # další snímek
            if idx < total - 1:
                idx += 1
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if not ret:
                    idx -= 1
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                frame = aplikuj_rotaci(frame, rotace)

        elif key == ord('b') or key == 8:   # B nebo Backspace = zpět
            if idx > 0:
                idx -= 1
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                frame = aplikuj_rotaci(frame, rotace)

        elif key == 13:              # ENTER = ořež
            cap.release()
            cv2.destroyWindow(nazev_okna)
            if idx == 0:
                print(f"  [{nazev}] Prvni snimek — nic k oriznutí, preskakuji.")
                return
            _orez_video(video_path, idx, fps, w, h)
            return

        elif key == ord('q'):        # přeskoč
            print(f"  [{nazev}] Preskoceno.")
            cap.release()
            cv2.destroyWindow(nazev_okna)
            return

    cap.release()
    cv2.destroyWindow(nazev_okna)


def _orez_video(video_path, start_frame, fps, w, h):
    """
    Přepíše video — zachová jen snímky od start_frame dál.
    Používá ffmpeg pokud je dostupný (rychlé, bezztrátové),
    jinak OpenCV (pomalé ale funguje vždy).
    """
    nazev = os.path.basename(video_path)
    start_sec = start_frame / fps
    tmp_path  = video_path + ".tmp.mp4"

    # Zkus ffmpeg — rychlý a zachová kvalitu
    ffmpeg_ok = False
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start_sec), "-i", video_path,
             "-c", "copy", tmp_path],
            capture_output=True, timeout=60
        )
        if result.returncode == 0 and os.path.exists(tmp_path):
            os.replace(tmp_path, video_path)
            ffmpeg_ok = True
            print(f"  [{nazev}] Oriznut od snimku {start_frame} "
                  f"({start_sec:.2f}s) — ffmpeg OK")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not ffmpeg_ok:
        # Záloha — OpenCV překóduje snímek po snímku
        print(f"  [{nazev}] ffmpeg nedostupny — pouzivam OpenCV (pomalejsi)...")
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out    = cv2.VideoWriter(tmp_path, fourcc, fps, (w, h))

        snimku = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            out.write(frame)
            snimku += 1

        cap.release()
        out.release()

        if snimku > 0 and os.path.exists(tmp_path):
            os.replace(tmp_path, video_path)
            print(f"  [{nazev}] Oriznut od snimku {start_frame} "
                  f"— zachovano {snimku} snimku")
        else:
            print(f"  [{nazev}] CHYBA: Oriznuti selhalo")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


# =========================================================
# HLAVNÍ KÓD
# =========================================================

print("=" * 55)
print("VIDEO TRIMMER — orizeže zacatek videi")
print("=" * 55)
print("MEZERNIK = dalsi snimek")
print("B        = predchozi snimek")
print("ENTER    = orez od tohoto snimku dal")
print("Q        = preskoc toto video")
print("=" * 55)

videa = []
for slozka in SLOZKY:
    nalezena = sorted(glob.glob(os.path.join(slozka, "*.mp4")))
    videa.extend(nalezena)
    print(f"  {slozka}: {len(nalezena)} videi")

if not videa:
    print("CHYBA: Zadna videa nenalezena.")
    sys.exit(1)

print(f"\nCelkem {len(videa)} videi.\n")

for i, video in enumerate(videa):
    print(f"[{i+1}/{len(videa)}] {video}")
    trim_video(video)

print("\n" + "=" * 55)
print("HOTOVO — vsechna videa zpracovana.")
print("=" * 55)