"""Universo operable, en un solo lugar. Debe coincidir con `v_current_risk_limits.universe`, que es lo que la base
hace cumplir: si cambia allá (siempre por decisión del usuario), cambia aquí.

- 2026-09-23: BTC, ETH, SOL, LINK y ONDO.
- 2026-10-07: el usuario promovió S-CHANNEL-1D-WIDE a dinero real y sumó sus 10 pares.
TimesFM sigue con los 5 originales: la tabla `forecasts` los fija y más series no caben en la RAM de esta PC.
"""
ORIGINAL = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT")
WIDE = ("BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "TRXUSDT", "LTCUSDT", "DOTUSDT", "BCHUSDT", "NEARUSDT")
UNIVERSE = ORIGINAL + WIDE
# Pares que vigila alguna estrategia LIVE_ELIGIBLE de canal: S-CHANNEL-1D (sin ONDO, historia corta) y su versión WIDE.
CHANNEL_SYMBOLS = tuple(s for s in UNIVERSE if s != "ONDOUSDT")
TIMESFM_SYMBOLS = ORIGINAL
