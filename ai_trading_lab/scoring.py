"""Puntuación objetiva de una decisión con el precio que vino después.

Supuestos conservadores, porque dentro de una vela de 1h no se sabe qué ocurrió primero:
  * La compra es una orden límite en entry_high: llena si una vela toca la zona, al menor
    entre la apertura y entry_high.
  * En la vela del llenado solo cuenta el stop, nunca el target.
  * Si en una misma vela se tocan stop y target, gana el stop.
"""
from dataclasses import dataclass, field

SCORER_VERSION = "1.0.0"
TAKER_FEE = 0.001  # 0,1 % por lado: comisión real de la subcuenta (spot_getAccount, 2026-09-23)


@dataclass
class Score:
    outcome: str
    fill_price: float | None = None
    exit_price: float | None = None
    r_multiple: float | None = None
    r_multiple_after_fees: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    details: dict = field(default_factory=dict)


def score_no_trade(reference_price, candles):
    """Para HOLD/DO_NOTHING: cuánto se movió el precio, para juzgar si quedarse fuera fue sensato."""
    if not candles:
        return Score("NO_TRADE", details={"candles": 0})
    high = max(c.high for c in candles)
    low = min(c.low for c in candles)
    return Score(
        "NO_TRADE",
        details={
            "reference_price": reference_price,
            "max_up_pct": round((high / reference_price - 1) * 100, 3),
            "max_down_pct": round((low / reference_price - 1) * 100, 3),
            "close_change_pct": round((candles[-1].close / reference_price - 1) * 100, 3),
            "candles": len(candles),
        },
    )


def score_buy(entry_low, entry_high, invalidation, target, candles, valid_until_ms, fee_rate=TAKER_FEE):
    """Puntúa una compra spot contra target (T1) e invalidación, sobre velas posteriores a la decisión."""
    if not (invalidation < entry_low <= entry_high < target):
        raise ValueError("Niveles incoherentes: se esperaba invalidation < entry_low <= entry_high < target")

    fill_index = fill_price = None
    for i, c in enumerate(candles):
        if c.open_time >= valid_until_ms:
            break
        if c.low <= entry_high and c.high >= entry_low:
            fill_index, fill_price = i, min(c.open, entry_high)
            break
    if fill_index is None:
        return Score("NOT_FILLED", details={"candles": len(candles)})

    risk = fill_price - invalidation
    max_high = min_low = fill_price
    for i in range(fill_index, len(candles)):
        c = candles[i]
        min_low = min(min_low, c.low)
        if c.low <= invalidation:
            return _closed("STOP_HIT", fill_price, invalidation, risk, max_high, min_low, fee_rate, i - fill_index)
        max_high = max(max_high, c.high)
        if i > fill_index and c.high >= target:
            return _closed("TARGET_HIT", fill_price, target, risk, max_high, min_low, fee_rate, i - fill_index)

    return _closed("OPEN_AT_HORIZON", fill_price, candles[-1].close, risk, max_high, min_low, fee_rate,
                   len(candles) - 1 - fill_index)


def _closed(outcome, fill, exit_price, risk, max_high, min_low, fee_rate, bars_held):
    r = (exit_price - fill) / risk
    fees_in_r = (fill + exit_price) * fee_rate / risk
    return Score(
        outcome,
        fill_price=fill,
        exit_price=exit_price,
        r_multiple=round(r, 4),
        r_multiple_after_fees=round(r - fees_in_r, 4),
        mfe_pct=round((max_high / fill - 1) * 100, 3),
        mae_pct=round((min_low / fill - 1) * 100, 3),
        details={"bars_held": bars_held, "fees_in_r": round(fees_in_r, 4)},
    )
