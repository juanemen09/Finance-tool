"""Inserta los pronósticos de TimesFM y puntúa los que ya vencieron frente al precio real y al paseo aleatorio.

  python -m tools.tsfm_ingest --dir data/raw/tsfm --insert
Lee los pronósticos pendientes con el rol dashboard_reader y escribe con lab_ingest (solo INSERT).
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from ai_trading_lab.candles import fetch_klines
from ai_trading_lab.forecasting import score, to_sql_statements
from dashboard.config import load_env

PENDING = ("select f.id, f.symbol, f.horizon_days, f.last_close, f.quantiles, f.benchmark, f.target_close_time "
           "from forecasts f left join forecast_outcomes o on o.forecast_id = f.id "
           "where o.id is null and f.target_close_time <= now() order by f.target_close_time limit 500")


def realized_close(symbol, target_iso):
    """Cierre de la vela diaria que termina en target_close_time (su apertura es 24 h antes)."""
    target_ms = int(datetime.fromisoformat(str(target_iso)).timestamp() * 1000)
    candles = fetch_klines(symbol, "1d", limit=1, start_ms=target_ms - 86_400_000)
    if not candles or candles[0].close_time + 1 != target_ms:
        return None
    return candles[0].close


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default="data/raw/tsfm")
    parser.add_argument("--insert", action="store_true")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    env = load_env()
    forecasts = []
    for path in sorted(Path(args.dir).glob("*.json"))[-3:]:  # los últimos cierres; los duplicados se ignoran
        forecasts += json.loads(path.read_text(encoding="utf-8"))["rows"]

    outcomes = []
    reader = env.get("DASHBOARD_DATABASE_URL", "")
    if "dashboard_reader" in reader:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(reader, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                             connect_timeout=15) as conn:
            pending = conn.execute(PENDING).fetchall()
        for row in pending:
            close = realized_close(row["symbol"], row["target_close_time"].isoformat())
            if close is not None:
                outcomes.append({"forecast_id": row["id"], **score(
                    {k: (float(v) if k == "last_close" else v) for k, v in row.items()}, close)})

    summary = {"forecasts_read": len(forecasts), "outcomes": len(outcomes),
               "direction_hits": sum(1 for o in outcomes if o["direction_hit"]),
               "beats_benchmark": sum(1 for o in outcomes if o["pinball_model"] < o["pinball_benchmark"])}
    if args.insert:
        url = env.get("INGEST_DATABASE_URL", "")
        if "lab_ingest" not in url:
            sys.exit("Falta INGEST_DATABASE_URL con el rol lab_ingest en .env")
        import psycopg
        with psycopg.connect(url, autocommit=True, prepare_threshold=None, connect_timeout=15) as conn:
            summary["inserted"] = [conn.execute(sql).rowcount for sql in to_sql_statements(forecasts, outcomes, "claude")]
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
