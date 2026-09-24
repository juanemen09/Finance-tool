import unittest

import numpy as np

from ai_trading_lab.backtest import Signals
from ai_trading_lab.strategies import CATALOG, grid
from ai_trading_lab.validation import (
    bootstrap_mean_ci, deflated_sharpe, hard_test, plateau_fraction, summarize, walk_forward_windows,
)
from tests.synthetic import planted_edge, random_walk

YEARS_3 = 3 * 8760


def rebound_after_drop(bars, p):
    """Compra tras una caída de una vela mayor que el umbral; la regla que el edge sembrado recompensa."""
    prev = np.concatenate(([np.nan], bars.close[:-1]))
    entries = (bars.close / prev - 1) < -p["drop"]
    n = len(bars)
    return Signals(entries, np.full(n, np.nan), np.full(n, np.nan), max_hold=p["hold"])


REBOUND_GRID = grid(drop=[0.02, 0.025], hold=[4, 5, 6])


class StatsTest(unittest.TestCase):
    def test_summary_drawdown_and_profit_factor(self):
        s = summarize([0.1, -0.05, 0.1, -0.1])
        self.assertAlmostEqual(s["profit_factor"], 0.2 / 0.15)
        self.assertLess(s["max_drawdown"], 0)

    def test_bootstrap_ci_brackets_true_mean(self):
        r = np.random.default_rng(0).normal(0.01, 0.02, 400)
        lo, hi = bootstrap_mean_ci(r, np.random.default_rng(1), n_boot=2000)
        self.assertLess(lo, 0.01)
        self.assertGreater(hi, 0.01)

    def test_deflated_sharpe_penalizes_many_trials(self):
        r = np.random.default_rng(3).normal(0.004, 0.02, 200)
        trial_sharpes = np.random.default_rng(4).normal(0, 0.1, 200)
        self.assertGreater(deflated_sharpe(r, 1, trial_sharpes), deflated_sharpe(r, 200, trial_sharpes))

    def test_walk_forward_windows_never_overlap_test_periods(self):
        w = walk_forward_windows(100, 40, 20)
        self.assertEqual(w, [((0, 40), (40, 60)), ((20, 60), (60, 80)), ((40, 80), (80, 100))])

    def test_plateau_counts_single_parameter_neighbors(self):
        key = lambda a, b: (("a", a), ("b", b))
        means = {key(1, 1): 0.01, key(2, 1): 0.02, key(1, 2): -0.01, key(2, 2): 0.03}
        self.assertEqual(plateau_fraction(means, {"a": 1, "b": 1}), 0.5)


class ChronologyTest(unittest.TestCase):
    def test_pooled_returns_follow_entry_time_across_symbols(self):
        from ai_trading_lab.backtest import Trade
        from ai_trading_lab.validation import chronological_returns
        from tests.synthetic import bars as make_bars

        b = make_bars(*[(100, 101, 99, 100)] * 10)

        def trade(entry_idx, ret):
            return Trade(entry_idx - 1, entry_idx, entry_idx + 1, 100, 100, "TIME", ret, ret, 0, 0)

        trades = {"A": [trade(2, 0.01), trade(8, 0.03)], "B": [trade(5, 0.02)]}
        self.assertEqual(chronological_returns(trades, {"A": b, "B": b}), [0.01, 0.02, 0.03])


class CalibrationTest(unittest.TestCase):
    """La prueba de que el test sirve: rechaza el azar y detecta un edge real."""

    def test_rejects_catalog_strategies_on_random_walks(self):
        passes = []
        for seed in range(4):
            rng = np.random.default_rng(100 + seed)
            data = {"A": random_walk(YEARS_3, rng), "B": random_walk(YEARS_3, rng)}
            for name, (strategy, params_grid) in CATALOG.items():
                report = hard_test(strategy, params_grid[:6], data, seed=seed)
                passes.append((seed, name, report["verdict"]))
        false_positives = [p for p in passes if p[2] == "PASS"]
        self.assertEqual(false_positives, [], f"falsos positivos: {false_positives}")

    def test_rejects_rebound_rule_when_there_is_no_edge(self):
        data = {"A": random_walk(YEARS_3, np.random.default_rng(5))}
        self.assertEqual(hard_test(rebound_after_drop, REBOUND_GRID, data)["verdict"], "FAIL")

    def test_detects_planted_edge(self):
        rng = np.random.default_rng(11)
        data = {"A": planted_edge(YEARS_3, rng), "B": planted_edge(YEARS_3, rng)}
        report = hard_test(rebound_after_drop, REBOUND_GRID, data)
        failed = {k: v for k, v in report["checks"].items() if not v["passed"]}
        self.assertEqual(report["verdict"], "PASS", f"chequeos fallidos: {failed}")
        self.assertTrue(report["holdout_used"])


if __name__ == "__main__":
    unittest.main()
