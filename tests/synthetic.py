"""Mercados sintéticos para calibrar el hard testing."""
import numpy as np

from ai_trading_lab.backtest import Bars

HOUR_MS = 3_600_000
START_MS = 1_577_836_800_000  # 2020-01-01T00:00Z


def random_walk(n_bars, rng, vol=0.006, start=100.0):
    """Paseo aleatorio sin deriva: ninguna regla puede tener edge real aquí."""
    return _bars_from_returns(rng.normal(0, vol, n_bars), rng, vol, start)


def planted_edge(n_bars, rng, vol=0.006, start=100.0, event_rate=0.02, drop=-0.03, rebound=0.006, rebound_bars=5):
    """Paseo aleatorio con un edge sembrado: tras una caída brusca, las 5 velas siguientes suben en promedio."""
    rets = rng.normal(0, vol, n_bars)
    i = 50
    while i < n_bars - rebound_bars - 1:
        if rng.random() < event_rate:
            rets[i] = drop
            rets[i + 1: i + 1 + rebound_bars] += rebound
            i += rebound_bars + 1
        else:
            i += 1
    return _bars_from_returns(rets, rng, vol, start)


def _bars_from_returns(rets, rng, vol, start):
    close = start * np.cumprod(1 + rets)
    open_ = np.concatenate(([start], close[:-1]))
    wick = np.abs(rng.normal(0, vol / 2, (2, len(rets))))
    high = np.maximum(open_, close) * (1 + wick[0])
    low = np.minimum(open_, close) * (1 - wick[1])
    t = START_MS + np.arange(len(rets), dtype=np.int64) * HOUR_MS
    return Bars(t, open_, high, low, close, np.ones(len(rets)))


def bars(*ohlc):
    a = np.array(ohlc, float)
    t = START_MS + np.arange(len(a), dtype=np.int64) * HOUR_MS
    return Bars(t, a[:, 0], a[:, 1], a[:, 2], a[:, 3], np.ones(len(a)))


def with_sentiment(b, rng):
    """Series de sentimiento sintéticas sin relación con el precio, para las familias que las exigen."""
    features = {"fear_greed": rng.uniform(0, 100, len(b)), "funding": rng.normal(3e-4, 3e-4, len(b))}
    return Bars(b.open_time, b.open, b.high, b.low, b.close, b.volume, features=features)
