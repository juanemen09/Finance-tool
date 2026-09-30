"""Abre el modo TV del centro de mando a pantalla completa en el segundo monitor.

  C:\\Python314\\pythonw.exe tools\\tv_launch.py   (tarea «AI Trading Lab\\Modo TV», al iniciar sesión)
  python -m tools.tv_launch --primary            (para probarlo en el monitor principal)

Si el panel no está corriendo lo arranca sin ventana. Si no hay segundo monitor no abre nada, porque el modo TV
a pantalla completa taparía el monitor de trabajo. Chrome usa un perfil propio, sin las sesiones del usuario.
Para cerrarlo: Alt+F4 con la TV enfocada.
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765
LOG = ROOT / "data" / "raw" / "tv" / "log.txt"
PROFILE = Path(os.environ.get("LOCALAPPDATA", str(ROOT / "data" / "raw"))) / "ai-trading-lab" / "tv-chrome"
CHROME_CANDIDATES = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
)


def log(line):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")


def monitors():
    """Rectángulos (left, top, right, bottom, primario) de las pantallas conectadas, según Windows."""
    found = []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                              wintypes.LPARAM)

    def callback(handle, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info))
        r = info.rcMonitor
        found.append((r.left, r.top, r.right, r.bottom, bool(info.dwFlags & 1)))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(callback), 0)
    return found


def pick_screen(screens, allow_primary=False):
    """La pantalla secundaria más grande (la TV); la principal solo si se pide expresamente."""
    secondary = [s for s in screens if not s[4]]
    if secondary:
        return max(secondary, key=lambda s: (s[2] - s[0]) * (s[3] - s[1]))
    primary = [s for s in screens if s[4]]
    return primary[0] if allow_primary and primary else None


def chrome_args(chrome, url, screen, profile):
    left, top, right, bottom, _ = screen
    # La ventana nace dentro de la TV (lejos del borde, por si Windows escala las coordenadas) y --kiosk la
    # agranda a pantalla completa en esa misma pantalla.
    x, y = left + (right - left) // 4, top + (bottom - top) // 4
    return [str(chrome), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-session-crashed-bubble", f"--window-position={x},{y}", "--window-size=1280,720",
            "--kiosk", f"--app={url}"]


def panel_up(port=PORT):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/tv", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def start_panel(port=PORT):
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    out = open(LOG.with_name("panel.txt"), "a", encoding="utf-8")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe), "-m", "dashboard", "--no-browser", "--port", str(port)], cwd=ROOT,
                     stdout=out, stderr=out, stdin=subprocess.DEVNULL, creationflags=flags)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--primary", action="store_true", help="abrir en el monitor principal si no hay otro")
    args = parser.parse_args(argv)

    screen = pick_screen(monitors(), allow_primary=args.primary)
    if screen is None:
        log("sin segundo monitor: no se abre el modo TV")
        return 0
    if not panel_up():
        start_panel()
        for _ in range(60):
            time.sleep(1)
            if panel_up():
                break
        else:
            log("el panel no respondió en 60 s (revisa data/raw/tv/panel.txt)")
            return 1
    # Solo rutas absolutas: sin LOCALAPPDATA el candidato sería relativo al directorio actual.
    chrome = next((c for c in CHROME_CANDIDATES if c.is_absolute() and c.exists()), None)
    if chrome is None:
        log("no se encontró Chrome ni Edge")
        return 1
    subprocess.Popen(chrome_args(chrome, f"http://127.0.0.1:{PORT}/tv", screen, PROFILE))
    log(f"modo TV abierto en la pantalla {screen[:4]} con {chrome.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
