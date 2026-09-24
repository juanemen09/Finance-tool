"""Velas para el gráfico, desde la API pública de Binance (sin claves), con los niveles del canal diario."""
import math
import re
import threading
import time

import numpy as np

from ai_trading_lab.candles import closed_only, fetch_klines
from ai_trading_lab.strategies import rolling_max, rolling_min

UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT")
INTERVALS = ("1h", "4h", "1d")
CACHE_SECONDS = 60
# S-CHANNEL-1D: entra si el cierre supera el máximo de 20 días; sale si pierde el mínimo de 10.
ENTRY_LOOKBACK, EXIT_LOOKBACK = 20, 10


class MarketError(ValueError):
    pass


def validate_candles_request(symbol, interval):
    if symbol not in UNIVERSE or interval not in INTERVALS or not re.fullmatch(r"[A-Z]+", symbol):
        raise MarketError("símbolo o temporalidad fuera del universo")
    return symbol, interval


def _level(value):
    return None if value is None or math.isnan(value) else float(value)


def candles_payload(symbol, interval, candles):
    rows = [{"time": c.open_time // 1000, "open": c.open, "high": c.high, "low": c.low, "close": c.close,
             "volume": c.volume} for c in candles]
    payload = {"symbol": symbol, "interval": interval, "candles": rows, "channel": []}
    if interval == "1d" and candles:
        high = np.array([c.high for c in candles])
        low = np.array([c.low for c in candles])
        entry, exit_ = rolling_max(high, ENTRY_LOOKBACK), rolling_min(low, EXIT_LOOKBACK)
        payload["channel"] = [{"time": r["time"], "entry_level": _level(e), "exit_level": _level(x)}
                              for r, e, x in zip(rows, entry, exit_)]
    return payload


class CandleCache:
    def __init__(self, fetch=fetch_klines):
        self._fetch, self._lock, self._cache = fetch, threading.Lock(), {}

    def get(self, symbol, interval):
        symbol, interval = validate_candles_request(symbol, interval)
        key = (symbol, interval)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
                return hit[1]
        payload = candles_payload(symbol, interval, closed_only(self._fetch(symbol, interval, limit=300)))
        with self._lock:
            self._cache[key] = (time.monotonic(), payload)
        return payload
