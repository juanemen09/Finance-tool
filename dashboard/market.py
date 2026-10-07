"""Datos de mercado públicos para el panel: velas de Binance con el canal diario y liquidez tokenizada (DefiLlama)."""
import json
import math
import re
import threading
import time
import urllib.request

import numpy as np

from ai_trading_lab.candles import closed_only, fetch_klines
from ai_trading_lab.sentiment_history import STABLECOIN_URL, growth_series, parse_stablecoin_history
from ai_trading_lab.strategies import rolling_max, rolling_min

from ai_trading_lab.universe import CHANNEL_SYMBOLS, UNIVERSE  # noqa: E402  (15 pares desde el 2026-10-07)
INTERVALS = ("1h", "4h", "1d")
CACHE_SECONDS = 60
RADAR_SECONDS = 60  # 14 pares; una ruptura diaria no necesita más y la IP comparte límite con los agentes
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


def radar_row(symbol, candles, now_ms=None):
    """Precio en vivo frente a los niveles que decidirán en el próximo cierre diario: la compra si el cierre supera
    el máximo de las 20 velas cerradas y la salida si pierde el mínimo de las 10."""
    closed = closed_only(candles, now_ms)
    if len(closed) < ENTRY_LOOKBACK or not candles:
        raise MarketError(f"{symbol}: faltan velas diarias para el canal")
    price = candles[-1].close  # la vela en formación: su cierre provisional es el precio actual
    entry = max(c.high for c in closed[-ENTRY_LOOKBACK:])
    exit_ = min(c.low for c in closed[-EXIT_LOOKBACK:])
    return {"symbol": symbol, "price": price, "last_close": closed[-1].close, "entry_level": entry,
            "exit_level": exit_, "gap_to_entry": entry / price - 1, "in_strategy": symbol in CHANNEL_SYMBOLS}


class RadarCache:
    def __init__(self, fetch=fetch_klines):
        self._fetch, self._refresh, self._at, self._value = fetch, threading.Lock(), 0.0, None

    def get(self):
        if self._value is not None and time.monotonic() - self._at <= RADAR_SECONDS:
            return self._value
        # Un solo hilo consulta a Binance; si tarda, los demás reciben el radar anterior en vez de quedar en cola.
        if not self._refresh.acquire(blocking=self._value is None):
            return self._value
        try:
            if self._value is None or time.monotonic() - self._at > RADAR_SECONDS:
                rows = []
                for s in UNIVERSE:
                    try:
                        rows.append(radar_row(s, self._fetch(s, "1d", limit=ENTRY_LOOKBACK + 5)))
                    except Exception as error:  # un par caído no apaga el radar de los demás
                        rows.append({"symbol": s, "error": type(error).__name__, "in_strategy": s in CHANNEL_SYMBOLS})
                self._value, self._at = {"rows": rows}, time.monotonic()
            return self._value
        finally:
            self._refresh.release()


def liquidity_payload(series, days=365):
    """Oferta de stablecoins del último año y su crecimiento a 30 días (con el dato del día anterior, igual que
    en el hard test)."""
    growth = growth_series(series, window=30, lag_days=1)
    recent = sorted(series)[-days:]
    return {"supply": [{"time": d // 1000, "value": series[d]} for d in recent],
            "growth_30d": [{"time": d // 1000, "value": growth[d]} for d in recent if d in growth]}


class LiquidityCache:
    SECONDS = 3600

    def __init__(self, fetch=None):
        self._fetch = fetch or (lambda: json.load(urllib.request.urlopen(urllib.request.Request(
            STABLECOIN_URL, headers={"User-Agent": "ai-trading-lab/1.0 (dashboard)"}), timeout=30)))
        self._lock, self._at, self._value = threading.Lock(), 0.0, None

    def get(self):
        with self._lock:
            if self._value is None or time.monotonic() - self._at > self.SECONDS:
                self._value = liquidity_payload(parse_stablecoin_history(self._fetch()))
                self._at = time.monotonic()
            return self._value
