"""Familias de estrategias formalizadas. Cada una es causal: la señal en i solo mira velas <= i.

Una estrategia es f(bars, params) -> Signals. El catálogo guarda la rejilla de parámetros que se
pre-registra antes de probar; ampliarla después cuenta como otro intento.
"""
import numpy as np

from ai_trading_lab.backtest import Signals


def ema(values, period):
    alpha = 2 / (period + 1)
    out = np.empty_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def atr(bars, period=14):
    prev_close = np.concatenate(([bars.close[0]], bars.close[:-1]))
    tr = np.maximum(bars.high - bars.low, np.maximum(abs(bars.high - prev_close), abs(bars.low - prev_close)))
    out = np.empty_like(tr)
    out[: period] = np.nan
    if len(tr) > period:
        out[period] = tr[1: period + 1].mean()
        for i in range(period + 1, len(tr)):
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def _rolling(values, window, reducer):
    """reducer de las `window` velas anteriores a i (sin incluir i)."""
    out = np.full(len(values), np.nan)
    if len(values) > window:
        out[window:] = reducer(np.lib.stride_tricks.sliding_window_view(values, window)[: len(values) - window], axis=1)
    return out


def rolling_max(values, window):
    return _rolling(values, window, np.max)


def rolling_min(values, window):
    return _rolling(values, window, np.min)


def _atr_exits(bars, entries, a, stop_atr, target_atr):
    entries = entries & ~np.isnan(a)
    stop = np.where(entries, bars.close - stop_atr * a, np.nan)
    target = np.where(entries, bars.close + target_atr * a, np.nan)
    return entries, stop, target


def breakout(bars, p):
    """Ruptura de Donchian: cierre por encima del máximo de las N velas previas (seguimiento de tendencia)."""
    a = atr(bars)
    entries = bars.close > rolling_max(bars.high, p["lookback"])
    entries, stop, target = _atr_exits(bars, entries, a, p["stop_atr"], p["target_atr"])
    return Signals(entries, stop, target, max_hold=p["max_hold"])


def ema_trend(bars, p):
    """Cruce al alza de la EMA rápida sobre la lenta (seguimiento de tendencia)."""
    fast, slow = ema(bars.close, p["fast"]), ema(bars.close, p["slow"])
    above = fast > slow
    entries = above & np.concatenate(([False], ~above[:-1]))
    entries[: p["slow"]] = False
    entries, stop, target = _atr_exits(bars, entries, atr(bars), p["stop_atr"], p["target_atr"])
    return Signals(entries, stop, target, max_hold=p["max_hold"])


def drop_reversal(bars, p):
    """Reversión de corto plazo: compra tras una vela bajista extrema dentro de una tendencia mayor alcista."""
    a = atr(bars)
    prev_close = np.concatenate(([np.nan], bars.close[:-1]))
    drop = (prev_close - bars.close) / a
    trend_ok = bars.close > ema(bars.close, p["trend_ema"]) if p["trend_ema"] else np.ones(len(bars), bool)
    entries = (drop > p["drop_atr"]) & trend_ok & ~np.isnan(a)
    entries[: max(p["trend_ema"], 15)] = False
    stop = np.where(entries, bars.close - p["stop_atr"] * a, np.nan)
    return Signals(entries, stop, np.full(len(bars), np.nan), max_hold=p["max_hold"])


def channel_trend(bars, p):
    """Canal de Donchian con salida por el canal contrario (reglas tipo tortuga): entra al superar el máximo
    de N velas y sale al perder el mínimo de M; stop de protección en k ATR. Pensada para 4h y diario, donde
    pocas operaciones largas diluyen el coste."""
    a = atr(bars)
    entries = (bars.close > rolling_max(bars.high, p["entry_lookback"])) & ~np.isnan(a)
    exits = bars.close < rolling_min(bars.low, p["exit_lookback"])
    stop = np.where(entries, bars.close - p["stop_atr"] * a, np.nan)
    return Signals(entries, stop, np.full(len(bars), np.nan), exits=exits)


def tsmom(bars, p):
    """Momentum de serie temporal: entra cuando el retorno de las últimas N velas supera el umbral y sale
    cuando deja de ser positivo; stop de protección en k ATR."""
    n = p["lookback"]
    past = np.concatenate((np.full(n, np.nan), bars.close[:-n]))
    momentum = bars.close / past - 1
    on = momentum > p["threshold"]
    entries = on & ~np.concatenate(([False], on[:-1]))
    a = atr(bars)
    entries &= ~np.isnan(a)
    stop = np.where(entries, bars.close - p["stop_atr"] * a, np.nan)
    return Signals(entries, stop, np.full(len(bars), np.nan), exits=momentum <= 0)


def squeeze_breakout(bars, p):
    """Compresión de volatilidad seguida de ruptura: el ancho de Bollinger de la vela previa está cerca de su
    mínimo de `lookback` velas y el cierre supera la banda superior."""
    w = p["bb"]
    windows = np.lib.stride_tricks.sliding_window_view(bars.close, w)
    ma = np.full(len(bars), np.nan)
    sd = np.full(len(bars), np.nan)
    ma[w - 1:] = windows.mean(axis=1)
    sd[w - 1:] = windows.std(axis=1)
    width = 4 * sd / ma
    prev_width = np.concatenate(([np.nan], width[:-1]))
    squeezed = prev_width <= 1.1 * rolling_min(width, p["lookback"])
    entries = squeezed & (bars.close > ma + 2 * sd)
    entries, stop, target = _atr_exits(bars, entries, atr(bars), p["stop_atr"], p["target_atr"])
    return Signals(entries, stop, target, max_hold=p["max_hold"])


def grid(**axes):
    """Producto cartesiano de parámetros, en orden estable."""
    combos = [{}]
    for key, values in axes.items():
        combos = [dict(c, **{key: v}) for c in combos for v in values]
    return combos


CATALOG = {
    "breakout": (breakout, grid(lookback=[24, 48, 96], stop_atr=[1.5, 2.5], target_atr=[3.0, 5.0], max_hold=[48])),
    "ema_trend": (ema_trend, grid(fast=[12, 24], slow=[72, 168], stop_atr=[1.5, 2.5], target_atr=[3.0, 5.0], max_hold=[72])),
    "drop_reversal": (drop_reversal, grid(drop_atr=[2.0, 2.5, 3.0], trend_ema=[0, 200], stop_atr=[1.5, 2.5], max_hold=[6, 12])),
    # Familias de baja rotación para 4h y diario (los parámetros están en velas de la temporalidad probada).
    "channel_trend": (channel_trend, grid(entry_lookback=[20, 55], exit_lookback=[10, 20], stop_atr=[2.0, 3.0])),
    "tsmom": (tsmom, grid(lookback=[20, 60, 120], threshold=[0.0, 0.05], stop_atr=[2.5])),
    "squeeze_breakout": (squeeze_breakout, grid(bb=[20], lookback=[60, 120], stop_atr=[1.5, 2.5],
                                                target_atr=[3.0, 5.0], max_hold=[30])),
}
