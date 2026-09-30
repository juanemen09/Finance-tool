"""Pulso horario para la TV: la última nota del orquestador (data/raw/horas/memoria.jsonl), el resultado de la última
hora ya evaluada y el estado del servicio residente de TimesFM. Solo lee archivos locales y 127.0.0.1:8766."""
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY = ROOT / "data" / "raw" / "horas" / "memoria.jsonl"
CACHE_SECONDS = 30
TAIL = 12
NOTE_KEYS = ("nombre", "hora", "ciclo", "mercado", "guardia", "timesfm", "timesfm_error", "sentimiento", "similares", "agentes")


def tail_records(path=MEMORY, n=TAIL):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:  # una línea a medio escribir no tumba la TV
            continue
    return out


def build_hourly(records, tsfm_status):
    from tools.orquestador import evaluate, note_name
    service = tsfm_status or {"cargado": False, "error": "El servicio de TimesFM no responde (se arranca al iniciar sesión)."}
    if not records:
        return {"nota": None, "evaluada": None, "timesfm_servicio": service}
    last = records[-1]
    note = {k: last.get(k) for k in NOTE_KEYS}
    note["finbert"] = (last.get("contenedores") or {}).get("finbert")
    by_name = {r["nombre"]: r for r in records}
    evaluated = None
    for r in reversed(records):
        later = by_name.get(note_name(datetime.fromisoformat(r["hora"]) + timedelta(hours=4)))
        if later:
            out = evaluate(r, later)
            evaluated = {"nombre": r["nombre"], "resultado": out["resultado"], "tags": out["tags"],
                         "agentes": r.get("agentes") or {}}
            break
    return {"nota": note, "evaluada": evaluated, "timesfm_servicio": service}


class HourlyCache:
    def __init__(self, path=MEMORY, status=None):
        from tools import tsfm_client
        self._path, self._status = path, status or tsfm_client.status
        self._lock, self._at, self._value = threading.Lock(), 0.0, None

    def get(self):
        with self._lock:
            if self._value is None or time.monotonic() - self._at > CACHE_SECONDS:
                self._value = build_hourly(tail_records(self._path), self._status())
                self._at = time.monotonic()
            return self._value
