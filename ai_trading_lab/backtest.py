"""Motor de backtest de una sola posición, pensado para no poder hacerse trampas.

Contrato con las estrategias: la señal de la vela i solo puede usar datos hasta el cierre de i, y la
entrada ocurre en la apertura de i+1. Dentro de una vela no se sabe qué pasó primero, así que:
  * si la vela toca stop y target, gana el stop;
  * si la apertura ya salta el stop o el target, se sale en la apertura (el hueco se paga o se cobra entero).
"""
from dataclasses import dataclass, field

import numpy as np

POSITION_USDT = 7.0
MIN_NOTIONAL_USDT = 5.0


@dataclass(frozen=True)
class Bars:
    open_time: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    # Series externas alineadas vela a vela (p. ej. Fear & Greed); el valor de i solo puede usar datos hasta i.
    features: dict | None = field(default=None, compare=False, repr=False)

    def __len__(self):
        return len(self.close)

    def slice(self, start, stop):
        arrays = (a[start:stop] for a in (self.open_time, self.open, self.high, self.low, self.close, self.volume))
        features = {k: v[start:stop] for k, v in self.features.items()} if self.features else None
        return Bars(*arrays, features=features)


@dataclass(frozen=True)
class Costs:
    fee_rate: float = 0.001  # comisión real de la subcuenta, por lado
    slippage: float = 0.0005  # por lado, sobre el precio de referencia

    def scaled(self, factor):
        return Costs(self.fee_rate * factor, self.slippage * factor)


@dataclass(frozen=True)
class Signals:
    entries: np.ndarray  # bool, decidido al cierre de la vela i
    stop: np.ndarray  # precio absoluto fijado en la vela de la señal; nan = sin stop
    target: np.ndarray  # precio absoluto; nan = sin target
    max_hold: int | None = None  # velas desde la entrada, incluida
    exits: np.ndarray | None = None  # bool; salida en la apertura siguiente


@dataclass
class Trade:
    signal_idx: int
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_return: float
    net_return: float
    mfe: float
    mae: float
    below_min_notional: bool = field(default=False)

    @property
    def bars_held(self):
        return self.exit_idx - self.entry_idx + 1


def run(bars, signals, costs=Costs(), entry_window=None):
    """Ejecuta las señales. entry_window=(inicio, fin) limita dónde pueden nacer operaciones."""
    n = len(bars)
    o, h, l, c = bars.open, bars.high, bars.low, bars.close
    candidates = np.flatnonzero(signals.entries[: n - 1])
    if entry_window is not None:
        start, stop = entry_window
        candidates = candidates[(candidates >= start) & (candidates < stop)]

    trades = []
    free_from = 0
    for i in candidates:
        if i < free_from:
            continue
        e = i + 1
        stop, target = signals.stop[i], signals.target[i]
        has_stop, has_target = not np.isnan(stop), not np.isnan(target)
        exit_idx = exit_raw = reason = None
        hi = lo = o[e]
        for j in range(e, n):
            # Hueco en la apertura (incluida la de entrada: un stop por encima del precio sale al instante).
            if has_stop and o[j] <= stop:
                exit_idx, exit_raw, reason = j, o[j], "STOP"
                break
            if has_target and o[j] >= target:
                exit_idx, exit_raw, reason = j, o[j], "TARGET"
                break
            lo = min(lo, l[j])
            if has_stop and l[j] <= stop:
                exit_idx, exit_raw, reason = j, stop, "STOP"
                break
            hi = max(hi, h[j])
            if has_target and h[j] >= target:
                exit_idx, exit_raw, reason = j, target, "TARGET"
                break
            if signals.max_hold and j - e + 1 >= signals.max_hold:
                exit_idx, exit_raw, reason = j, c[j], "TIME"
                break
            if signals.exits is not None and signals.exits[j] and j + 1 < n:
                exit_idx, exit_raw, reason = j + 1, o[j + 1], "SIGNAL"
                break
        if exit_idx is None:
            exit_idx, exit_raw, reason = n - 1, c[n - 1], "END"

        buy = o[e] * (1 + costs.slippage) * (1 + costs.fee_rate)
        sell = exit_raw * (1 - costs.slippage) * (1 - costs.fee_rate)
        net = sell / buy - 1
        trades.append(Trade(
            signal_idx=int(i), entry_idx=int(e), exit_idx=int(exit_idx),
            entry_price=float(o[e]), exit_price=float(exit_raw), exit_reason=reason,
            gross_return=float(exit_raw / o[e] - 1), net_return=float(net),
            mfe=float(hi / o[e] - 1), mae=float(lo / o[e] - 1),
            below_min_notional=POSITION_USDT * (1 + net) < MIN_NOTIONAL_USDT,
        ))
        free_from = exit_idx
    return trades


def lookahead_violations(strategy, bars, params, checkpoints):
    """Índices donde la señal cambia al quitar datos futuros: debería devolver una lista vacía."""
    full = strategy(bars, params)
    bad = []
    for k in checkpoints:
        partial = strategy(bars.slice(0, k + 1), params)
        same_entry = bool(full.entries[k]) == bool(partial.entries[k])
        same_stop = np.isclose(full.stop[k], partial.stop[k], equal_nan=True)
        same_target = np.isclose(full.target[k], partial.target[k], equal_nan=True)
        same_exit = full.exits is None or bool(full.exits[k]) == bool(partial.exits[k])
        if not (same_entry and same_stop and same_target and same_exit):
            bad.append(int(k))
    return bad
