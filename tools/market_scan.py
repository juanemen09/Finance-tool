"""Foto de mercado del universo en 1h y 4h, con velas cerradas de la API pública de Binance.

Uso:  python -m tools.market_scan            -> resumen legible
      python -m tools.market_scan --json     -> JSON para guardar en analyses.details
"""
import argparse
import json
import time
from datetime import datetime, timezone

from ai_trading_lab.candles import closed_only, fetch_klines, get_json
from ai_trading_lab.indicators import atr, ema, relative_volume, rsi, swing_points

UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT"]
TIMEFRAMES = {"4h": 30, "1h": 50}  # velas para el rango reciente


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")


def frame_summary(candles, range_bars):
    closes = [c.close for c in candles]
    price = closes[-1]
    atr_value = atr(candles)
    swing_highs, swing_lows = swing_points(candles)
    recent = candles[-range_bars:]
    high, low = max(c.high for c in recent), min(c.low for c in recent)
    return {
        "last_closed_at": iso(candles[-1].close_time + 1),
        "close": price,
        "ema20": round(ema(closes, 20)[-1], 6),
        "ema50": round(ema(closes, 50)[-1], 6),
        "ema200": round(ema(closes, 200)[-1], 6),
        "rsi14": round(rsi(closes), 2),
        "atr14": round(atr_value, 6),
        "atr_pct": round(atr_value / price * 100, 3),
        "rvol_last": round(relative_volume(candles, 1), 2),
        "rvol_last3": round(relative_volume(candles, 3), 2),
        "change_6_bars_pct": round((price / closes[-7] - 1) * 100, 2),
        "change_24_bars_pct": round((price / closes[-25] - 1) * 100, 2),
        "range_high": high,
        "range_low": low,
        "position_in_range_pct": round((price - low) / (high - low) * 100, 1) if high > low else None,
        "swing_highs": [p for _, p in swing_highs[-4:]],
        "swing_lows": [p for _, p in swing_lows[-4:]],
    }


def scan():
    now_ms = get_json("/api/v3/time")["serverTime"]
    symbols = json.dumps(UNIVERSE, separators=(",", ":"))
    filters = {
        s["symbol"]: next(f for f in s["filters"] if f["filterType"] in ("NOTIONAL", "MIN_NOTIONAL"))
        for s in get_json("/api/v3/exchangeInfo", {"symbols": symbols})["symbols"]
    }
    result = {"market_data_as_of": iso(now_ms), "source": "Binance public REST /api/v3", "assets": {}}
    for symbol in UNIVERSE:
        ticker = get_json("/api/v3/ticker/24hr", {"symbol": symbol})
        asset = {
            "last_price": float(ticker["lastPrice"]),
            "change_24h_pct": float(ticker["priceChangePercent"]),
            "quote_volume_24h": float(ticker["quoteVolume"]),
            "min_notional_usdt": float(filters[symbol]["minNotional"]),
        }
        for interval, range_bars in TIMEFRAMES.items():
            candles = closed_only(fetch_klines(symbol, interval, limit=300), now_ms)
            asset[interval] = frame_summary(candles, range_bars)
        result["assets"][symbol] = asset
    return result


def print_text(snapshot):
    print(f"Datos a {snapshot['market_data_as_of']} ({snapshot['source']})")
    for symbol, a in snapshot["assets"].items():
        print(f"\n{symbol}  {a['last_price']}  24h {a['change_24h_pct']:+.2f}%  minNotional {a['min_notional_usdt']}")
        for tf in TIMEFRAMES:
            f = a[tf]
            trend = "sobre" if f["close"] > f["ema50"] else "bajo"
            print(f"  {tf}: cierre {f['close']} ({trend} EMA50 {f['ema50']}), EMA200 {f['ema200']}, "
                  f"RSI {f['rsi14']}, ATR {f['atr_pct']}%, RVOL {f['rvol_last']}/{f['rvol_last3']}, "
                  f"rango {f['range_low']}-{f['range_high']} ({f['position_in_range_pct']}%)")
            print(f"       máximos {f['swing_highs']}  mínimos {f['swing_lows']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    data = scan()
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print_text(data)
