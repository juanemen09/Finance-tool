"""Señal actual (última vela cerrada) de las estrategias en PAPER o LIVE_ELIGIBLE, para `strategy_signals`.

Entrada: JSON con [{strategy_id, implementation_ref, params, symbols, bar_interval}], exportado de Supabase.
Uso:  python -m tools.strategy_signals active.json --cycle-id 2026-09-24T12Z
"""
import argparse
import json
import sys
from datetime import datetime, timezone

import numpy as np

import urllib.request

from ai_trading_lab.backtest import Bars
from ai_trading_lab.candles import closed_only, fetch_klines
from ai_trading_lab.sentiment_history import (
    STABLECOIN_URL, attach_daily_features, growth_series, parse_stablecoin_history,
)
from tools.run_hard_test import resolve


def live_series(name):
    """Serie externa al día para las estrategias con filtro. Se descarga fresca: el archivo congelado del hard
    test no se toca (su hash identifica los datos de la prueba)."""
    if name == "stablecoin_growth_30d":
        request = urllib.request.Request(STABLECOIN_URL, headers={"User-Agent": "ai-trading-lab/1.0 (signals)"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return growth_series(parse_stablecoin_history(json.load(response)), window=30, lag_days=1)
    raise ValueError(f"la serie {name!r} no está disponible en vivo")


def with_live_features(bars, params, loader=live_series):
    name = params.get("filter")
    return attach_daily_features(bars, {name: loader(name)}) if name else bars


def recent_bars(symbol, interval, limit=1000):
    candles = closed_only(fetch_klines(symbol, interval, limit=limit))
    a = np.array([(c.open_time, c.open, c.high, c.low, c.close, c.volume, c.close_time) for c in candles], float)
    return Bars(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]), int(a[-1, 6])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("active_json")
    parser.add_argument("--cycle-id", required=True)
    args = parser.parse_args()
    rows = []
    for item in json.load(open(args.active_json, encoding="utf-8")):
        strategy = resolve(item["implementation_ref"])
        for symbol in item["symbols"]:
            bars, close_ms = recent_bars(symbol, item.get("bar_interval", "1h"))
            bars = with_live_features(bars, item["params"])
            sig = strategy(bars, item["params"])
            fired = bool(sig.entries[-1])
            rows.append({
                "strategy_id": item["strategy_id"],
                "cycle_id": args.cycle_id,
                "symbol": symbol,
                "signal": "ENTRY" if fired else "NONE",
                "entry_price": float(bars.close[-1]) if fired else None,
                "stop": None if not fired or np.isnan(sig.stop[-1]) else float(sig.stop[-1]),
                "target": None if not fired or np.isnan(sig.target[-1]) else float(sig.target[-1]),
                "bar_close_time": datetime.fromtimestamp((close_ms + 1) / 1000, timezone.utc).isoformat(),
            })
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
