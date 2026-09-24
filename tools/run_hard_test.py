"""Ejecuta el protocolo de hard testing de un pre-registro y devuelve la fila para `backtest_runs`.

Entrada: JSON con el pre-registro exportado de Supabase más `implementation_ref` y `n_trials_total`
(de v_trial_count). La estrategia debe estar en el catálogo del repo: el nombre viene de la base de datos
y no se usa para importar código arbitrario.

Uso:  python -m tools.run_hard_test prereg.json > run.json
      python -m tools.run_hard_test prereg.json --kind PAPER_REVIEW --since 2026-10-01 --params '{"lookback": 48, ...}'
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone

import numpy as np

from ai_trading_lab import data_store
from ai_trading_lab.backtest import Costs, run
from ai_trading_lab.sentiment_history import (
    attach_daily_features, daily_funding, growth_series, load_fear_greed, load_funding_events, load_stablecoin_supply,
)
from ai_trading_lab.strategies import CATALOG
from ai_trading_lab.validation import DEFAULT_THRESHOLDS, hard_test, incremental_test, summarize

MIN_FORWARD_TRADES = 20


def resolve(implementation_ref):
    name = implementation_ref.split(":")[-1]
    if name not in CATALOG:
        raise SystemExit(f"'{implementation_ref}' no está en el catálogo {sorted(CATALOG)}; no se ejecuta.")
    return CATALOG[name][0]


def code_commit():
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "ai_trading_lab", "tools"],
                           capture_output=True, text=True).stdout.strip()
    return head + ("+dirty" if dirty else "")


def load_features(pre, bars_by_symbol, data_hashes):
    """Añade las series de sentimiento que pide la rejilla (parámetro `filter`) y registra su hash."""
    filters = sorted({p["filter"] for p in pre["param_grid"] if "filter" in p})
    if not filters:
        return bars_by_symbol
    if pre["bar_interval"] != "1d":
        raise SystemExit("Las series de sentimiento son diarias: solo se prueban con bar_interval '1d'.")
    shared = {}
    if "fear_greed" in filters:
        shared["fear_greed"], data_hashes["fear_greed"] = load_fear_greed()
    if "stablecoin_growth_30d" in filters:
        supply, data_hashes["stablecoin_supply"] = load_stablecoin_supply()
        shared["stablecoin_growth_30d"] = growth_series(supply, window=30, lag_days=1)
    out = {}
    for symbol, bars in bars_by_symbol.items():
        series = dict(shared)
        if "funding" in filters:
            events, data_hashes[f"funding:{symbol}"] = load_funding_events(symbol)
            series["funding"] = daily_funding(events)
        out[symbol] = attach_daily_features(bars, series)
    return out


def incremental_checks(pre, strategy, bars_by_symbol, costs):
    """Si el pre-registro compara contra una base, la variante debe aportar antes de gastar la reserva."""
    th = {**DEFAULT_THRESHOLDS, **(pre.get("thresholds") or {})}
    cfg = th.get("incremental")
    if not cfg:
        return None, {}
    result = incremental_test(strategy, pre["param_grid"], cfg["baseline_params"], bars_by_symbol, costs=costs,
                              holdout_bars=pre["holdout_bars"], train_bars=pre["train_bars"],
                              test_bars=pre["test_bars"], min_trades_selection=th["min_trades_selection"],
                              null_sims=cfg.get("null_sims", 200))
    pct_min, blocked_min = cfg.get("null_percentile_min", 95.0), cfg.get("min_blocked_signals", 10)
    checks = {
        "increment_mean_diff": {"value": result["mean_diff"], "threshold": 0.0,
                                "passed": result["mean_diff"] is not None and result["mean_diff"] > 0},
        "increment_null_percentile": {"value": result["null_percentile"], "threshold": pct_min,
                                      "passed": result["null_percentile"] is not None
                                      and result["null_percentile"] >= pct_min},
        "increment_blocked_signals": {"value": result["blocked_signals"], "threshold": blocked_min,
                                      "passed": result["blocked_signals"] >= blocked_min},
    }
    return result, checks


def forward_review(strategy, params, bars_by_symbol, since_ms, costs, expected_lower):
    """Papel o re-test: parámetros fijos, solo velas posteriores a `since`. None si aún faltan operaciones."""
    returns = []
    for bars in bars_by_symbol.values():
        start = int(np.searchsorted(bars.open_time, since_ms))
        returns += [t.net_return for t in run(bars, strategy(bars, params), costs, (start, len(bars) - 1))]
    summary = summarize(returns)
    if summary["n"] < MIN_FORWARD_TRADES:
        return None, summary
    passed = summary["mean"] > 0 and summary["mean"] >= expected_lower
    return ("PASS" if passed else "FAIL"), summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prereg_json")
    parser.add_argument("--kind", choices=["HARD_TEST", "PAPER_REVIEW", "RETEST"], default="HARD_TEST")
    parser.add_argument("--since", help="AAAA-MM-DD, inicio del periodo hacia delante (PAPER_REVIEW/RETEST)")
    parser.add_argument("--params", help="JSON con los parámetros fijados (PAPER_REVIEW/RETEST)")
    parser.add_argument("--expected-lower", type=float, default=0.0,
                        help="límite inferior esperado del retorno medio (del bootstrap del HARD_TEST)")
    args = parser.parse_args()

    pre = json.load(open(args.prereg_json, encoding="utf-8"))
    strategy = resolve(pre["implementation_ref"])
    costs = Costs(**pre["costs"]) if pre.get("costs") else Costs()
    loaded = {s: data_store.load(s, pre["bar_interval"]) for s in pre["symbols"]}
    bars_by_symbol = {s: b for s, (b, _) in loaded.items()}
    data_hashes = {s: h for s, (_, h) in loaded.items()}
    bars_by_symbol = load_features(pre, bars_by_symbol, data_hashes)
    now = datetime.now(timezone.utc)

    if args.kind == "HARD_TEST":
        incremental, inc_checks = incremental_checks(pre, strategy, bars_by_symbol, costs)
        report = hard_test(strategy, pre["param_grid"], bars_by_symbol, costs=costs,
                           holdout_bars=pre["holdout_bars"], train_bars=pre["train_bars"], test_bars=pre["test_bars"],
                           n_trials_total=pre["n_trials_total"], thresholds=pre.get("thresholds"),
                           allow_holdout=all(c["passed"] for c in inc_checks.values()))
        if incremental is not None:
            report["incremental"] = incremental
            report["checks"].update(inc_checks)
            report["verdict"] = "PASS" if all(c["passed"] for c in report["checks"].values()) else "FAIL"
        report["bars_from"] = {s: int(b.open_time[0]) for s, b in bars_by_symbol.items()}
        verdict, holdout_used = report["verdict"], report["holdout_used"]
    else:
        since_ms = int(datetime.combine(date.fromisoformat(args.since), datetime.min.time(), timezone.utc).timestamp() * 1000)
        verdict, summary = forward_review(strategy, json.loads(args.params), bars_by_symbol, since_ms, costs,
                                          args.expected_lower)
        if verdict is None:
            print(json.dumps({"status": "INSUFFICIENT_TRADES", "summary": summary,
                              "note": f"Se necesitan {MIN_FORWARD_TRADES} operaciones; no registrar run."}))
            return
        report, holdout_used = {"forward_since": args.since, "params": json.loads(args.params), "forward": summary,
                                "expected_lower": args.expected_lower}, False

    print(json.dumps({
        "run_id": f"RUN-{pre['prereg_id']}-{args.kind}-{now:%Y%m%dT%H%MZ}",
        "prereg_id": pre["prereg_id"],
        "kind": args.kind,
        "code_commit": code_commit(),
        "data_hashes": data_hashes,
        "n_trials_total": pre["n_trials_total"],
        "verdict": verdict,
        "holdout_used": holdout_used,
        "report": report,
    }, indent=2, default=float))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
