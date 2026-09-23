"""Indicadores técnicos sobre listas de Candle, sin dependencias externas."""


def ema(values, period):
    alpha = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def rsi(closes, period=14):
    """RSI de Wilder."""
    if len(closes) <= period:
        raise ValueError(f"RSI{period} necesita más de {period} cierres")
    gain = loss = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gain += max(delta, 0)
        loss += max(-delta, 0)
    gain /= period
    loss /= period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = (gain * (period - 1) + max(delta, 0)) / period
        loss = (loss * (period - 1) + max(-delta, 0)) / period
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def atr(candles, period=14):
    """ATR de Wilder."""
    if len(candles) <= period:
        raise ValueError(f"ATR{period} necesita más de {period} velas")
    true_ranges = [candles[0].high - candles[0].low]
    for prev, cur in zip(candles, candles[1:]):
        true_ranges.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    value = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def relative_volume(candles, bars=1, baseline=20):
    """Volumen medio de las últimas `bars` velas frente a la media de las `baseline` anteriores."""
    recent = candles[-bars:]
    base = candles[-bars - baseline:-bars]
    base_avg = sum(c.volume for c in base) / len(base)
    return (sum(c.volume for c in recent) / len(recent)) / base_avg


def swing_points(candles, wing=3, lookback=120):
    """Máximos y mínimos fractales: extremos de una ventana de 2*wing+1 velas.

    Devuelve (highs, lows) como listas de (índice_negativo, precio), del más antiguo al más reciente.
    """
    window = candles[-lookback:]
    n = len(window)
    highs, lows = [], []
    for i in range(wing, n - wing):
        span = window[i - wing:i + wing + 1]
        if window[i].high == max(c.high for c in span):
            highs.append((i - n, window[i].high))
        if window[i].low == min(c.low for c in span):
            lows.append((i - n, window[i].low))
    return highs, lows
