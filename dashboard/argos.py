"""Pestaña «Seguridad» del centro de mando: Argos-Atlas (argos-atlas/) embebido en el panel.

El panel no reenvía nada de Argos: solo comprueba si responde y le dice al navegador dónde está. La dirección tiene que
ser de este mismo PC (http en 127.0.0.1 o localhost); cualquier otra se ignora, porque el panel la autoriza como marco.
"""
import json
import logging
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_URL = "http://127.0.0.1:8787"
ARGOS_DIR = Path(__file__).resolve().parent.parent / "argos-atlas"
CHECK_SECONDS = 10
log = logging.getLogger("dashboard")


def argos_origin(value):
    """Origen http de Argos si es de este PC; si no, el de por defecto."""
    parts = urlsplit((value or "").strip())
    try:
        port = parts.port
    except ValueError:
        port = None
    if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost"} or not port or parts.path not in {"", "/"}:
        return DEFAULT_URL
    return f"http://{parts.hostname}:{port}"


class ArgosStatus:
    """Estado de Argos-Atlas para /api/argos, consultado como mucho cada 10 s."""

    def __init__(self, url=DEFAULT_URL, opener=urllib.request.urlopen):
        self.url, self._open, self._lock, self._at, self._value = argos_origin(url), opener, threading.Lock(), 0.0, None

    def _probe(self):
        try:
            with self._open(f"{self.url}/api/estado", timeout=1.5) as r:
                estado = json.loads(r.read())
        except (urllib.error.URLError, OSError, ValueError):
            return {"ok": False, "url": self.url, "arranque": "docker compose up -d --build  (en la carpeta argos-atlas)"}
        presencia = estado.get("presencia") or {}
        return {"ok": True, "url": self.url, "presencia": {"modo": presencia.get("modo"), "sensor": presencia.get("sensor")}}

    def __call__(self):
        with self._lock:
            if self._value is None or time.monotonic() - self._at > CHECK_SECONDS:
                self._value, self._at = self._probe(), time.monotonic()
            return self._value


def start_if_down(status, runner=subprocess.Popen, which=shutil.which):
    """Si Argos no responde, lo levanta con Docker en segundo plano. Devuelve un mensaje para la consola."""
    if status()["ok"]:
        return "Argos-Atlas ya está en marcha."
    if which("docker") is None:
        return "Argos-Atlas no está en marcha y no encuentro Docker: abre Docker Desktop o arráncalo con npm (argos-atlas/README.md)."
    if not (ARGOS_DIR / "docker-compose.yml").exists():
        return "No encuentro argos-atlas/docker-compose.yml."
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # en Windows, sin ventana de consola extra
    try:
        runner(["docker", "compose", "up", "-d", "--build"], cwd=ARGOS_DIR, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, creationflags=flags)
    except OSError as error:
        return f"No pude arrancar Argos-Atlas con Docker: {error}"
    return "Arrancando Argos-Atlas con Docker (la primera vez tarda unos minutos en construirse)…"
