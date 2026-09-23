"""Puntúa decisiones del diario con el precio posterior de Binance.

Entrada: JSON con una lista de filas de `analyses` (exportadas con la consulta de docs/PROTOCOL.md).
Salida: JSON con filas listas para insertar en `decision_scores`.

Uso:  python -m tools.score_decisions analyses.json --horizon 24 > scores.json
"""
import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime

from ai_trading_lab.candles import HOUR_MS, closed_only, fetch_klines
from ai_trading_lab.scoring import SCORER_VERSION, score_buy, score_no_trade


def to_ms(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def candles_after(symbol, start_ms, horizon_hours):
    # Primera vela de 1h que abre después de la decisión: la vela en curso ya estaba "vista" en parte.
    first_open = (start_ms // HOUR_MS + 1) * HOUR_MS
    candles = fetch_klines(symbol, "1h", limit=horizon_hours, start_ms=first_open)
    return [c for c in closed_only(candles) if c.open_time < first_open + horizon_hours * HOUR_MS]


def score_row(row, horizon_hours):
    decided_ms = to_ms(row["market_data_as_of"])
    if row["proposed_action"] == "BUY_CANDIDATE":
        candles = candles_after(row["symbol"], decided_ms, horizon_hours)
        score = score_buy(
            float(row["entry_low"]), float(row["entry_high"]), float(row["invalidation"]),
            float(row["targets"][0]), candles, to_ms(row["valid_until"]),
        )
    else:
        symbol = row.get("symbol") or "BTCUSDT"  # sin símbolo: se mide contra el régimen de BTC
        candles = candles_after(symbol, decided_ms, horizon_hours)
        reference = fetch_klines(symbol, "1h", limit=1, end_ms=decided_ms)[0].close
        score = score_no_trade(reference, candles)
        score.details["symbol"] = symbol

    complete = len(candles) >= horizon_hours
    score.details["horizon_complete"] = complete
    return {
        "analysis_id": row["analysis_id"],
        "scorer_version": SCORER_VERSION,
        "horizon_hours": horizon_hours,
        **{k: v for k, v in asdict(score).items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analyses_json")
    parser.add_argument("--horizon", type=int, default=24, help="horas de velas de 1h tras la decisión")
    args = parser.parse_args()
    rows = json.load(open(args.analyses_json, encoding="utf-8"))
    scores = [score_row(r, args.horizon) for r in rows]
    pending = [s["analysis_id"] for s in scores if not s["details"]["horizon_complete"]]
    if pending:
        print(f"Aviso: horizonte incompleto (no insertar aún): {pending}", file=sys.stderr)
    print(json.dumps(scores, indent=2))


if __name__ == "__main__":
    main()
