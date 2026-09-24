import unittest

import numpy as np

from ai_trading_lab.backtest import Costs, Signals, lookahead_violations, run
from ai_trading_lab.strategies import CATALOG
from tests.synthetic import bars, random_walk, with_sentiment

NO_COSTS = Costs(0.0, 0.0)
NAN = np.nan


def signals_at(n, idx, stop=NAN, target=NAN, max_hold=None, exits=None):
    entries = np.zeros(n, bool)
    entries[idx] = True
    return Signals(entries, np.full(n, stop), np.full(n, target), max_hold, exits)


class EngineTest(unittest.TestCase):
    def test_enters_at_next_open_not_signal_close(self):
        b = bars((100, 101, 99, 100), (105, 106, 104, 105), (105, 107, 104, 106))
        [t] = run(b, signals_at(3, 0), NO_COSTS)
        self.assertEqual(t.entry_idx, 1)
        self.assertEqual(t.entry_price, 105)
        self.assertEqual(t.exit_reason, "END")

    def test_stop_wins_when_bar_touches_both(self):
        b = bars((100, 100, 100, 100), (100, 100, 99, 100), (100, 112, 94, 105))
        [t] = run(b, signals_at(3, 0, stop=95, target=110), NO_COSTS)
        self.assertEqual((t.exit_reason, t.exit_price), ("STOP", 95))

    def test_gap_below_stop_fills_at_open(self):
        b = bars((100, 100, 100, 100), (100, 101, 99, 100), (90, 91, 89, 90))
        [t] = run(b, signals_at(3, 0, stop=95), NO_COSTS)
        self.assertEqual((t.exit_reason, t.exit_price), ("STOP", 90))

    def test_time_exit_after_max_hold(self):
        b = bars(*[(100, 101, 99, 100)] * 6)
        [t] = run(b, signals_at(6, 0, max_hold=3), NO_COSTS)
        self.assertEqual((t.exit_reason, t.bars_held), ("TIME", 3))

    def test_exit_signal_leaves_at_next_open(self):
        b = bars((100, 101, 99, 100), (100, 101, 99, 100), (102, 103, 101, 102), (104, 105, 103, 104))
        exits = np.array([False, False, True, False])
        [t] = run(b, signals_at(4, 0, exits=exits), NO_COSTS)
        self.assertEqual((t.exit_reason, t.exit_idx, t.exit_price), ("SIGNAL", 3, 104))

    def test_costs_are_charged_on_both_sides(self):
        b = bars((100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100))
        [t] = run(b, signals_at(3, 0, max_hold=2), Costs(0.001, 0.0005))
        expected = (1 - 0.0005) * (1 - 0.001) / ((1 + 0.0005) * (1 + 0.001)) - 1
        self.assertAlmostEqual(t.net_return, expected)
        self.assertAlmostEqual(t.gross_return, 0.0)

    def test_one_position_at_a_time(self):
        entries_everywhere = Signals(np.ones(8, bool), np.full(8, NAN), np.full(8, NAN), max_hold=3)
        trades = run(bars(*[(100, 101, 99, 100)] * 8), entries_everywhere, NO_COSTS)
        for a, b in zip(trades, trades[1:]):
            self.assertGreaterEqual(b.entry_idx, a.exit_idx + 1)

    def test_entry_window_limits_where_trades_start(self):
        entries_everywhere = Signals(np.ones(10, bool), np.full(10, NAN), np.full(10, NAN), max_hold=1)
        trades = run(bars(*[(100, 101, 99, 100)] * 10), entries_everywhere, NO_COSTS, entry_window=(4, 6))
        self.assertEqual([t.signal_idx for t in trades], [4, 5])

    def test_flags_exit_below_min_notional(self):
        b = bars((100, 100, 100, 100), (100, 100, 60, 60), (60, 60, 60, 60))
        [t] = run(b, signals_at(3, 0), NO_COSTS)
        self.assertTrue(t.below_min_notional)


class LookaheadTest(unittest.TestCase):
    def test_catalog_strategies_never_use_future_bars(self):
        rng = np.random.default_rng(7)
        b = with_sentiment(random_walk(1500, rng), rng)
        checkpoints = range(250, 1499, 97)
        for name, (strategy, params_grid) in CATALOG.items():
            for params in params_grid[:3]:
                with self.subTest(strategy=name, params=params):
                    self.assertEqual(lookahead_violations(strategy, b, params, checkpoints), [])

    def test_detector_catches_an_exit_that_peeks(self):
        def peeking_exit(bars, p):
            n = len(bars)
            future = np.concatenate((bars.close[1:], [bars.close[-1]]))
            return Signals(np.ones(n, bool), np.full(n, NAN), np.full(n, NAN), exits=future < bars.close)

        b = random_walk(400, np.random.default_rng(2))
        self.assertNotEqual(lookahead_violations(peeking_exit, b, {}, range(100, 399, 10)), [])

    def test_detector_catches_a_cheating_strategy(self):
        def peeks(bars, p):
            future = np.concatenate((bars.close[1:], [bars.close[-1]]))
            n = len(bars)
            return Signals(future > bars.close, np.full(n, NAN), np.full(n, NAN), max_hold=1)

        b = random_walk(400, np.random.default_rng(1))
        self.assertNotEqual(lookahead_violations(peeks, b, {}, range(100, 399, 10)), [])


if __name__ == "__main__":
    unittest.main()
