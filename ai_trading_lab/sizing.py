"""Tamaño de una compra para que quepa en la autorización permanente (standing_authorizations).

La base estima la pérdida como auto_authorization_status: salto del stop desde el peor precio de la zona
(entry_high) más comisión y deslizamiento de ida y vuelta (0,15 % por lado). Con 7 USDT fijos, un stop a 2 ATR
en un activo volátil pasaba de 0,8 USDT y la compra nunca podía ejecutarse sola; el usuario pidió (2026-09-26)
achicar la posición hasta que quepa.
"""
import math

COST_PER_SIDE = 0.0015
MAX_POSITION_USDT = 7.0
# Binance exige 5 USDT por orden, también en la venta del stop: la cantidad comprada valorada al precio del stop
# debe superar ese mínimo, con un margen para el redondeo de la cantidad.
MIN_STOP_NOTIONAL = 5.1
# La base recalcula con los precios ya redondeados de la propuesta: un 0,5 % de holgura evita quedar justo encima.
LOSS_MARGIN = 0.995


def loss_fraction(entry_high, invalidation):
    return (entry_high - invalidation) / entry_high + 2 * COST_PER_SIDE


def auto_notional(entry_high, invalidation, max_loss_usdt=0.8, cap=MAX_POSITION_USDT):
    """Notional en USDT (centavos hacia abajo) y si la compra podría ejecutarse sola.

    - Si el tope de pérdida permite el máximo, se usa el máximo.
    - Si no, se achica hasta que la pérdida estimada quede en el tope.
    - Si achicarla deja el stop por debajo del mínimo de Binance, se propone el mínimo operable y hace falta el
      "autorizo" del usuario (auto_eligible = False).
    - Si ni el máximo alcanza el mínimo operable, no hay tamaño válido (notional_usdt = None).
    """
    if not entry_high > invalidation > 0:
        raise ValueError("el stop debe estar por debajo de la entrada")
    frac = loss_fraction(entry_high, invalidation)
    floor_notional = math.ceil(MIN_STOP_NOTIONAL * entry_high / invalidation * 100) / 100
    by_loss = math.floor(max_loss_usdt * LOSS_MARGIN / frac * 100) / 100
    notional = min(cap, by_loss)
    auto = notional >= floor_notional
    if not auto:
        notional = floor_notional if floor_notional <= cap else None
    return {"notional_usdt": notional, "auto_eligible": auto and notional is not None,
            "estimated_max_loss_usdt": round(notional * frac, 4) if notional else None,
            "min_operable_usdt": floor_notional}
