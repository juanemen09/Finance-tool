"""Señal actual (última vela cerrada) de las estrategias en PAPER o LIVE_ELIGIBLE, para `strategy_signals`.

Entrada: JSON con [{strategy_id, implementation_ref, params, symbols, bar_interval}], exportado de Supabase.
Uso:  python -m tools.strategy_signals active.json --cycle-id 2026-09-24T12Z
"""
import argparse
import json
import sys
from datetime import datetime, timezone

import numpy as np

from ai_trading_lab.backtest import Bars
from ai_trading_lab.candles import closed_only, fetch_klines
from tools.run_hard_test import resolve


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
