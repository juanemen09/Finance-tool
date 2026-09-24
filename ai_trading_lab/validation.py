"""Protocolo de hard testing: una estrategia solo pasa si sobrevive a todo lo que suele fabricar edges falsos.

Orden: rejilla en desarrollo -> walk-forward fuera de muestra -> chequeos estadísticos -> y solo si todo
pasa, una única evaluación en la reserva final.
"""
import math
from collections import Counter
from statistics import NormalDist

import numpy as np

from ai_trading_lab.backtest import Bars, Costs, run

HOURS_PER_YEAR = 8760
EULER_GAMMA = 0.5772156649

DEFAULT_THRESHOLDS = {
    "min_trades_dev": 100,
    "min_trades_oos": 30,
    "min_trades_holdout": 5,
    "bootstrap_ci_lower_gt": 0.0,
    "random_entry_percentile_min": 95.0,
    "plateau_fraction_min": 0.7,
    "double_cost_mean_gt": 0.0,
    "positive_year_fraction_min": 0.6,
    "deflated_sharpe_min": 0.95,
    # Operaciones mínimas en un tramo de entrenamiento para poder elegir parámetros por su estadístico t. Con
    # velas diarias (~7 operaciones por año y activo) 10 nunca se alcanzaba y se elegía siempre la primera
    # combinación de la rejilla; los pre-registros diarios nuevos lo fijan explícitamente.
    "min_trades_selection": 10,
}


# ---------------------------------------------------------------------------
# Estadística
# ---------------------------------------------------------------------------

def summarize(returns):
    r = np.asarray(returns, float)
    if len(r) == 0:
        return {"n": 0}
    equity = np.cumprod(1 + r)
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    wins, losses = r[r > 0], r[r <= 0]
    return {
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(np.median(r)),
        "std": float(r.std(ddof=1)) if len(r) > 1 else 0.0,
        "win_rate": float(len(wins) / len(r)),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "total_return": float(equity[-1] - 1),
        "max_drawdown": float((equity / peak - 1).min()),
    }


def bootstrap_mean_ci(returns, rng, n_boot=10_000, alpha=0.05):
    r = np.asarray(returns, float)
    means = r[rng.integers(0, len(r), size=(n_boot, len(r)))].mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def monte_carlo_drawdown(returns, rng, n_sims=2_000):
    """Distribución del máximo drawdown si las mismas operaciones hubieran llegado en otro orden."""
    r = np.asarray(returns, float)
    shuffled = r[np.argsort(rng.random((n_sims, len(r))), axis=1)]
    equity = np.cumprod(1 + shuffled, axis=1)
    peak = np.maximum.accumulate(np.concatenate((np.ones((n_sims, 1)), equity), axis=1), axis=1)[:, 1:]
    dd = (equity / peak - 1).min(axis=1)
    return {"p50": float(np.quantile(dd, 0.5)), "p95_worst": float(np.quantile(dd, 0.05))}


def deflated_sharpe(returns, n_trials, trial_sharpes):
    """Probabilidad de que el Sharpe por operación supere al máximo esperado por azar entre n_trials intentos
    (Bailey y López de Prado, 2014)."""
    r = np.asarray(returns, float)
    t = len(r)
    if t < 3 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)
    z = (r - r.mean()) / r.std(ddof=0)
    skew, kurt = float((z ** 3).mean()), float((z ** 4).mean())
    var_trials = float(np.var(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else 0.0
    nd = NormalDist()
    if n_trials > 1 and var_trials > 0:
        sr0 = math.sqrt(var_trials) * ((1 - EULER_GAMMA) * nd.inv_cdf(1 - 1 / n_trials)
                                       + EULER_GAMMA * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    else:
        sr0 = 0.0
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return 0.0
    return float(nd.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom)))


def random_entry_benchmark(bars_by_symbol, trades_by_symbol, windows_by_symbol, costs, rng, n_sims=1_000):
    """Media neta de operaciones con entradas al azar: mismo número por activo, mismas ventanas y
    duraciones sacadas de las de la estrategia. Salida al cierre tras esa duración."""
    sim_returns = []
    for symbol, trades in trades_by_symbol.items():
        if not trades:
            continue
        bars = bars_by_symbol[symbol]
        holds = np.array([t.bars_held for t in trades])
        allowed = np.concatenate([np.arange(a, b) for a, b in windows_by_symbol[symbol]])
        allowed = allowed[allowed + holds.max() + 1 < len(bars)]
        idx = rng.choice(allowed, size=(n_sims, len(trades)))
        hold = rng.choice(holds, size=(n_sims, len(trades)))
        buy = bars.open[idx + 1] * (1 + costs.slippage) * (1 + costs.fee_rate)
        sell = bars.close[idx + hold] * (1 - costs.slippage) * (1 - costs.fee_rate)
        sim_returns.append(sell / buy - 1)
    return np.concatenate(sim_returns, axis=1).mean(axis=1)


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def _score(returns, min_trades=10):
    """Criterio de selección en entrenamiento: estadístico t del retorno medio (premia constancia, no suerte)."""
    r = np.asarray(returns, float)
    if len(r) < max(min_trades, 2) or r.std(ddof=1) == 0:
        return -np.inf
    return r.mean() / r.std(ddof=1) * math.sqrt(len(r))


def walk_forward_windows(n_bars, train_bars, test_bars):
    windows, start = [], 0
    while start + train_bars + test_bars <= n_bars:
        windows.append(((start, start + train_bars), (start + train_bars, start + train_bars + test_bars)))
        start += test_bars
    return windows


def _param_key(params):
    return tuple(sorted(params.items()))


def plateau_fraction(dev_means, best):
    """Fracción de vecinos del mejor conjunto (difieren en un solo parámetro) con media positiva."""
    best_key = dict(best)
    neighbors = [m for key, m in dev_means.items()
                 if sum(dict(key)[k] != best_key[k] for k in best_key) == 1]
    if not neighbors:
        return 1.0 if dev_means[_param_key(best)] > 0 else 0.0
    return float(np.mean([m > 0 for m in neighbors]))


def hard_test(strategy, param_grid, bars_by_symbol, *, costs=Costs(), holdout_bars=4380,
              train_bars=8760, test_bars=2190, n_trials_total=None, thresholds=None, seed=0, allow_holdout=True):
    """Devuelve un informe con cada chequeo (valor, umbral, pasó) y el veredicto PASS/FAIL."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    rng = np.random.default_rng(seed)
    signals = {s: {_param_key(p): strategy(b, p) for p in param_grid} for s, b in bars_by_symbol.items()}
    dev_end = {s: len(b) - holdout_bars for s, b in bars_by_symbol.items()}

    # 1. Desarrollo completo: base para la meseta y la varianza de Sharpe entre intentos.
    dev_returns = {}
    for p in param_grid:
        k = _param_key(p)
        dev_returns[k] = [t.net_return for s, b in bars_by_symbol.items()
                          for t in run(b, signals[s][k], costs, (0, dev_end[s]))]
    dev_means = {k: (np.mean(r) if r else -np.inf) for k, r in dev_returns.items()}
    trial_sharpes = [np.mean(r) / np.std(r, ddof=1) for r in dev_returns.values() if len(r) > 2 and np.std(r) > 0]

    # 2. Walk-forward: elegir en cada tramo de entrenamiento, medir en el siguiente tramo de prueba.
    oos_trades = {s: [] for s in bars_by_symbol}
    oos_trades_2x = {s: [] for s in bars_by_symbol}
    oos_windows = {s: [] for s in bars_by_symbol}
    chosen = Counter()
    for s, b in bars_by_symbol.items():
        for (tr0, tr1), (te0, te1) in walk_forward_windows(dev_end[s], train_bars, test_bars):
            best = max(param_grid, key=lambda p: _score(
                [t.net_return for t in run(b, signals[s][_param_key(p)], costs, (tr0, tr1))], th["min_trades_selection"]))
            chosen[_param_key(best)] += 1
            sig = signals[s][_param_key(best)]
            oos_trades[s] += run(b, sig, costs, (te0, te1))
            oos_trades_2x[s] += run(b, sig, costs.scaled(2), (te0, te1))
            oos_windows[s].append((te0, te1))

    # Orden cronológico entre activos: la curva de capital y el drawdown solo tienen sentido en el tiempo.
    oos = np.array(chronological_returns(oos_trades, bars_by_symbol))
    oos_2x = np.array(chronological_returns(oos_trades_2x, bars_by_symbol))
    favorite = dict(chosen.most_common(1)[0][0]) if chosen else param_grid[0]
    n_trials = n_trials_total or len(param_grid)

    checks = {}

    def check(name, value, threshold, passed):
        checks[name] = {"value": value, "threshold": threshold, "passed": bool(passed)}

    check("trades_dev_favorite", len(dev_returns[_param_key(favorite)]), th["min_trades_dev"],
          len(dev_returns[_param_key(favorite)]) >= th["min_trades_dev"])
    check("trades_oos", int(len(oos)), th["min_trades_oos"], len(oos) >= th["min_trades_oos"])
    enough = len(oos) >= max(th["min_trades_oos"], 3)
    if enough:
        lo, hi = bootstrap_mean_ci(oos, rng)
        check("bootstrap_ci_lower", lo, th["bootstrap_ci_lower_gt"], lo > th["bootstrap_ci_lower_gt"])
        bench = random_entry_benchmark(bars_by_symbol, oos_trades, oos_windows, costs, rng)
        pct = float((bench < oos.mean()).mean() * 100)
        check("random_entry_percentile", pct, th["random_entry_percentile_min"], pct >= th["random_entry_percentile_min"])
        check("double_cost_mean", float(oos_2x.mean()), th["double_cost_mean_gt"], oos_2x.mean() > th["double_cost_mean_gt"])
        years = _yearly_means(oos_trades, bars_by_symbol)
        frac = float(np.mean([m > 0 for m in years.values()])) if years else 0.0
        check("positive_year_fraction", frac, th["positive_year_fraction_min"], frac >= th["positive_year_fraction_min"])
        dsr = deflated_sharpe(oos, n_trials, trial_sharpes)
        check("deflated_sharpe", dsr, th["deflated_sharpe_min"], dsr >= th["deflated_sharpe_min"])
    else:
        hi = None
        for name in ("bootstrap_ci_lower", "random_entry_percentile", "double_cost_mean",
                     "positive_year_fraction", "deflated_sharpe"):
            check(name, None, th.get(name), False)
    plateau = plateau_fraction(dev_means, favorite)
    check("parameter_plateau", plateau, th["plateau_fraction_min"], plateau >= th["plateau_fraction_min"])

    # 3. Reserva final: solo se consume si todo lo anterior pasó.
    # allow_holdout=False: otra prueba previa (p. ej. la incremental) ya falló y la reserva no debe gastarse.
    pre_holdout_pass = allow_holdout and all(c["passed"] for c in checks.values())
    holdout = None
    if pre_holdout_pass:
        k = _param_key(favorite)
        ho = [t.net_return for s, b in bars_by_symbol.items() for t in run(b, signals[s][k], costs, (dev_end[s], len(b) - 1))]
        holdout = summarize(ho)
        check("holdout_trades", len(ho), th["min_trades_holdout"], len(ho) >= th["min_trades_holdout"])
        check("holdout_mean", holdout.get("mean"), 0.0, bool(ho) and holdout["mean"] > 0)

    return {
        "verdict": "PASS" if all(c["passed"] for c in checks.values()) else "FAIL",
        "holdout_used": pre_holdout_pass,
        "favorite_params": favorite,
        "chosen_params_count": {str(dict(k)): v for k, v in chosen.items()},
        "n_trials": n_trials,
        "oos": summarize(oos),
        "oos_mean_ci_upper": hi,
        "oos_monte_carlo_drawdown": monte_carlo_drawdown(oos, rng) if enough else None,
        "holdout": holdout,
        "checks": checks,
        "costs": {"fee_rate": costs.fee_rate, "slippage": costs.slippage},
    }


def _paired_windows(strategy, param_grid, baseline_params, devs, costs, train_bars, test_bars, min_trades_selection):
    diffs, blocked, chosen = [], 0, Counter()
    for dev in devs:
        signals = {_param_key(p): strategy(dev, p) for p in param_grid}
        base = strategy(dev, baseline_params)
        for (tr0, tr1), (te0, te1) in walk_forward_windows(len(dev), train_bars, test_bars):
            best = max(param_grid, key=lambda p: _score(
                [t.net_return for t in run(dev, signals[_param_key(p)], costs, (tr0, tr1))], min_trades_selection))
            k = _param_key(best)
            chosen[k] += 1
            variant = sum(t.net_return for t in run(dev, signals[k], costs, (te0, te1)))
            baseline = sum(t.net_return for t in run(dev, base, costs, (te0, te1)))
            diffs.append(variant - baseline)
            blocked += int((base.entries[te0:te1] & ~signals[k].entries[te0:te1]).sum())
    return np.asarray(diffs, float), blocked, chosen


def _shifted(bars, rng):
    """Mismas series externas desplazadas en el tiempo: conservan su distribución y sus rachas, pero pierden
    cualquier relación con el precio."""
    offset = int(rng.integers(1, len(bars)))
    features = {k: np.roll(v, offset) for k, v in bars.features.items()}
    return Bars(bars.open_time, bars.open, bars.high, bars.low, bars.close, bars.volume, features=features)


def incremental_test(strategy, param_grid, baseline_params, bars_by_symbol, *, costs=Costs(), holdout_bars,
                     train_bars, test_bars, min_trades_selection=10, null_sims=200, seed=0):
    """¿Aporta el filtro? Walk-forward pareado solo sobre el desarrollo (la reserva ni se calcula): en cada
    tramo de prueba, la variante elegida en su entrenamiento contra la base, con las mismas velas.

    Ganarle a la base no basta: si la base pierde (costes), bloquear operaciones al azar también "mejora".
    Por eso la mejora se compara con la de la misma variante usando la serie externa desplazada en el tiempo
    (null_sims veces); null_percentile es el porcentaje de esos filtros de azar que quedan por debajo."""
    rng = np.random.default_rng(seed)
    devs = [b.slice(0, len(b) - holdout_bars) for b in bars_by_symbol.values()]
    args = (strategy, param_grid, baseline_params)
    rest = (costs, train_bars, test_bars, min_trades_selection)
    d, blocked, chosen = _paired_windows(*args, devs, *rest)
    lo, hi = bootstrap_mean_ci(d, rng) if len(d) >= 3 else (None, None)
    null = [_paired_windows(*args, [_shifted(dev, rng) for dev in devs], *rest)[0].mean() for _ in range(null_sims)]
    return {
        "n_windows": int(len(d)),
        "mean_diff": float(d.mean()) if len(d) else None,
        "ci_lower": lo,
        "ci_upper": hi,
        "windows_better": int((d > 0).sum()),
        "windows_worse": int((d < 0).sum()),
        "blocked_signals": blocked,
        "null_sims": null_sims,
        "null_mean_diff_median": float(np.median(null)) if null else None,
        "null_percentile": float((np.asarray(null) < d.mean()).mean() * 100) if null and len(d) else None,
        "chosen_params_count": {str(dict(k)): v for k, v in chosen.items()},
    }


def chronological_returns(trades_by_symbol, bars_by_symbol):
    """Retornos netos de todos los activos ordenados por hora de entrada."""
    timed = [(int(bars_by_symbol[s].open_time[t.entry_idx]), t.net_return)
             for s, trades in trades_by_symbol.items() for t in trades]
    return [r for _, r in sorted(timed, key=lambda x: x[0])]


def _yearly_means(trades_by_symbol, bars_by_symbol, min_trades=10):
    by_year = {}
    for s, trades in trades_by_symbol.items():
        for t in trades:
            year = int(np.datetime64(int(bars_by_symbol[s].open_time[t.entry_idx]), "ms").astype("datetime64[Y]").astype(int) + 1970)
            by_year.setdefault(year, []).append(t.net_return)
    return {y: float(np.mean(r)) for y, r in by_year.items() if len(r) >= min_trades}
