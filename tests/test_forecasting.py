import math
import unittest

import numpy as np

from ai_trading_lab import forecasting as f


def flat_logq(price):
    return [math.log(price * (1 + (q - 0.5) / 10)) for q in f.QUANTILES]


class Rows(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        self.closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 500)))

    def test_three_horizons_with_benchmark(self):
        logq = [flat_logq(self.closes[-1])] * 7
        rows = f.forecast_rows("BTCUSDT", 1_790_380_800_000, self.closes, logq)
        self.assertEqual([r["horizon_days"] for r in rows], [1, 3, 7])
        r7 = rows[2]
        self.assertEqual(r7["target_close_time"][:10], "2026-10-03")
        self.assertAlmostEqual(r7["quantiles"]["p50"], self.closes[-1], places=6)
        qs = [r7["benchmark"][f.qkey(q)] for q in f.QUANTILES]
        self.assertEqual(qs, sorted(qs))
        self.assertLess(r7["benchmark"]["p10"], self.closes[-1])
        self.assertGreater(r7["benchmark"]["p90"], self.closes[-1])

    def test_benchmark_widens_with_horizon(self):
        b1 = f.random_walk_benchmark(self.closes, 1)
        b7 = f.random_walk_benchmark(self.closes, 7)
        self.assertGreater(b7["p90"] - b7["p10"], b1["p90"] - b1["p10"])

    def test_short_history(self):
        with self.assertRaises(ValueError):
            f.random_walk_benchmark([100.0] * 20, 7)


class Scoring(unittest.TestCase):
    ROW = {"last_close": 100.0,
           "quantiles": {f.qkey(q): 100 + (q - 0.5) * 20 + 2 for q in f.QUANTILES},   # mediana 102: sube
           "benchmark": {f.qkey(q): 100 + (q - 0.5) * 40 for q in f.QUANTILES}}

    def test_right_direction_and_tighter_bands_win(self):
        s = f.score(self.ROW, 103.0)
        self.assertTrue(s["direction_hit"])
        self.assertTrue(s["inside_p10_p90"])
        self.assertLess(s["pinball_model"], s["pinball_benchmark"])

    def test_wrong_direction(self):
        s = f.score(self.ROW, 90.0)
        self.assertFalse(s["direction_hit"])
        self.assertFalse(s["inside_p10_p90"])

    def test_unchanged_price_has_no_direction(self):
        self.assertIsNone(f.score(self.ROW, 100.0)["direction_hit"])

    def test_pinball_perfect_median_is_small(self):
        q = {f.qkey(x): 100.0 for x in f.QUANTILES}
        self.assertEqual(f.pinball(q, 100.0), 0)


class Sql(unittest.TestCase):
    def test_statements_and_agent_validation(self):
        stmts = f.to_sql_statements([{"model": "m"}], [{"forecast_id": 1}], "claude")
        self.assertEqual(len(stmts), 2)
        self.assertTrue(all("on conflict do nothing" in s for s in stmts))
        with self.assertRaises(ValueError):
            f.to_sql_statements([], [], "x'; drop")


if __name__ == "__main__":
    unittest.main()
