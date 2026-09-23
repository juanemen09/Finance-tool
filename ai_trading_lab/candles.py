"""Velas de la API pública de Binance (sin autenticación)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

BASE_URL = "https://api.binance.com"
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Candle:
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def get_json(path, params=None, attempts=3):
    query = urllib.parse.urlencode(params or {})
    url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError):
            # Cortes de red puntuales ya ocurrieron; un error HTTP de Binance (4xx) no se reintenta.
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)


def parse_klines(rows):
    return [
        Candle(int(r[0]), int(r[6]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
        for r in rows
    ]


def fetch_klines(symbol, interval, limit=300, start_ms=None, end_ms=None):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms
    return parse_klines(get_json("/api/v3/klines", params))


def closed_only(candles, now_ms=None):
    # La última vela de Binance suele estar en formación; decidir con ella es mirar una vela a medias.
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    return [c for c in candles if c.close_time <= now_ms]
