"""Medidor del peso de peticiones que la IP de esta PC gasta en Binance (diagnóstico de los bloqueos -1003).

  C:\\Python314\\pythonw.exe tools\\binance_weight_monitor.py --hours 3

Cada 10 s pide la hora del servidor (peso 1) y anota el peso usado en el último minuto (cabecera
X-MBX-USED-WEIGHT-1M), que suma TODO lo que esta IP le pidió a Binance: nuestros scripts, el panel, los servidores MCP
de Claude y de Codex y cualquier otra cosa. Si el peso pasa de --umbral o Binance responde 429/418, guarda qué
procesos de python, node y uv estaban vivos y con qué comando, para saber quién hizo la ráfaga. Solo lectura.
"""
import argparse
import csv
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "binance_peso"
URL = "https://api.binance.com/api/v3/time"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROCS = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe' or Name='node.exe' or "
         "Name='uv.exe' or Name='uvx.exe' or Name='codex.exe' or Name='claude.exe'\" | "
         "Select-Object ProcessId, Name, CreationDate, CommandLine | ConvertTo-Json -Compress")


def sample():
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "ai-trading-lab/peso"}), timeout=10) as r:
            return r.status, int(r.headers.get("X-MBX-USED-WEIGHT-1M") or -1), ""
    except urllib.error.HTTPError as e:
        return e.code, int(e.headers.get("X-MBX-USED-WEIGHT-1M") or -1), e.read().decode("utf-8", "replace")[:200]
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, -1, type(e).__name__


def processes():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PROCS], capture_output=True, text=True,
                       timeout=60, creationflags=NO_WINDOW)
    try:
        rows = json.loads(r.stdout or "[]")
    except ValueError:
        return []
    rows = rows if isinstance(rows, list) else [rows]
    # Las líneas de comando pueden llevar claves (p. ej. ?api-key=): se recorta todo lo que sigue a "key" o "token".
    for p in rows:
        cmd = p.get("CommandLine") or ""
        for marker in ("key=", "KEY=", "token=", "secret="):
            if marker in cmd:
                cmd = cmd.split(marker)[0] + marker + "<oculto>"
        p["CommandLine"] = cmd[:400]
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=float, default=3)
    parser.add_argument("--umbral", type=int, default=1200)
    parser.add_argument("--cada", type=float, default=10)
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    csv_path, spikes_path = OUT / f"peso_{stamp}.csv", OUT / f"rafagas_{stamp}.jsonl"
    end, last_snapshot = time.monotonic() + args.hours * 3600, 0.0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["utc", "status", "peso_1m", "detalle"])
        while time.monotonic() < end:
            status, weight, detail = sample()
            now = datetime.now(timezone.utc)
            writer.writerow([now.isoformat(timespec="seconds"), status, weight, detail])
            f.flush()
            if (weight >= args.umbral or status in (418, 429)) and time.monotonic() - last_snapshot > 30:
                last_snapshot = time.monotonic()
                with open(spikes_path, "a", encoding="utf-8") as s:
                    s.write(json.dumps({"utc": now.isoformat(timespec="seconds"), "status": status, "peso_1m": weight,
                                        "detalle": detail, "procesos": processes()}, ensure_ascii=False) + "\n")
            time.sleep(args.cada)
    return 0


if __name__ == "__main__":
    sys.exit(main())
