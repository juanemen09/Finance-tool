"""Pronósticos de TimesFM 3.0 en papel y su puntuación frente a un paseo aleatorio.

Solo transforma datos (probado sin red ni modelo). El pronóstico corre en tools/tsfm_forecast.py y la inserción
y la puntuación en tools/tsfm_ingest.py.

Por qué solo hacia delante: TimesFM se preentrenó con datos públicos que casi seguro incluyen el historial de estos
precios. Un backtest mediría memoria, no capacidad. Solo los pronósticos hechos desde ahora, puntuados cuando
llega el precio real, dicen si el modelo sirve.
"""
import json
import math

import numpy as np

QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
HORIZONS = (1, 3, 7)
MODEL = "timesfm-3.0"
DAY_MS = 86_400_000


def qkey(q):
    return f"p{int(round(q * 100))}"


def quantiles_from_log(last_close, log_quantiles):
    """El modelo pronostica el log del precio; el exponencial conserva el orden, así que los cuantiles siguen siéndolo."""
    return {qkey(q): round(float(math.exp(v)), 8) for q, v in zip(QUANTILES, log_quantiles)}


def random_walk_benchmark(closes, horizon, lookback=365):
    """Referencia honesta: el último cierre por los cuantiles empíricos del retorno a `horizon` días del último año."""
    closes = np.asarray(closes, dtype=float)
    logs = np.log(closes[-(lookback + horizon):])
    rets = logs[horizon:] - logs[:-horizon]
    if len(rets) < 30:
        raise ValueError("historial insuficiente para la referencia")
    return {qkey(q): round(float(closes[-1] * math.exp(np.quantile(rets, q))), 8) for q in QUANTILES}


def forecast_rows(symbol, origin_close_ms, closes, log_quantiles_by_step):
    """Filas de `forecasts` para los horizontes 1, 3 y 7 días. `log_quantiles_by_step[h-1]` = 9 cuantiles del log."""
    last = float(closes[-1])
    rows = []
    for h in HORIZONS:
        rows.append({
            "model": MODEL, "symbol": symbol, "horizon_days": h,
            "origin_close_time": _iso(origin_close_ms),
            "target_close_time": _iso(origin_close_ms + h * DAY_MS),
            "last_close": last,
            "quantiles": quantiles_from_log(last, log_quantiles_by_step[h - 1]),
            "benchmark": random_walk_benchmark(closes, h),
        })
    return rows


def _iso(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def pinball(quantiles, realized):
    """Pérdida cuantil media (menor = mejor), en unidades de precio relativas al último cierre para poder promediar
    activos distintos."""
    total = 0.0
    for q in QUANTILES:
        pred = quantiles[qkey(q)]
        diff = realized - pred
        total += max(q * diff, (q - 1) * diff)
    return total / len(QUANTILES)


def score(row, realized_close):
    last = float(row["last_close"])
    med = float(row["quantiles"]["p50"])
    predicted = (med > last) - (med < last)
    actual = (realized_close > last) - (realized_close < last)
    return {
        "realized_close": realized_close,
        "pinball_model": round(pinball(row["quantiles"], realized_close) / last, 8),
        "pinball_benchmark": round(pinball(row["benchmark"], realized_close) / last, 8),
        "direction_hit": None if predicted == 0 or actual == 0 else predicted == actual,
        "inside_p10_p90": row["quantiles"]["p10"] <= realized_close <= row["quantiles"]["p90"],
    }


def to_sql_statements(forecasts, outcomes, agent_id):
    # Import tardío: el pronóstico corre en el entorno de TimesFM, que no tiene las dependencias del sentimiento.
    from ai_trading_lab.sentiment import AGENT_ID, _dollar_quote
    if not AGENT_ID.match(agent_id):
        raise ValueError(f"agent_id no válido: {agent_id!r}")
    out = []
    if forecasts:
        payload = _dollar_quote(json.dumps(forecasts))
        out.append(
            "insert into public.forecasts (model, symbol, horizon_days, origin_close_time, target_close_time, last_close, "
            "quantiles, benchmark, recorded_by_agent_id)\n"
            f"select model, symbol, horizon_days, origin_close_time, target_close_time, last_close, quantiles, benchmark, "
            f"'{agent_id}'\nfrom jsonb_to_recordset({payload}::jsonb) as x(model text, symbol text, horizon_days int, "
            "origin_close_time timestamptz, target_close_time timestamptz, last_close numeric, quantiles jsonb, "
            "benchmark jsonb)\non conflict do nothing;")
    if outcomes:
        payload = _dollar_quote(json.dumps(outcomes))
        out.append(
            "insert into public.forecast_outcomes (forecast_id, realized_close, pinball_model, pinball_benchmark, "
            "direction_hit, inside_p10_p90, recorded_by_agent_id)\n"
            f"select forecast_id, realized_close, pinball_model, pinball_benchmark, direction_hit, inside_p10_p90, "
            f"'{agent_id}'\nfrom jsonb_to_recordset({payload}::jsonb) as x(forecast_id bigint, realized_close numeric, "
            "pinball_model numeric, pinball_benchmark numeric, direction_hit boolean, inside_p10_p90 boolean)\n"
            "on conflict do nothing;")
    return out
