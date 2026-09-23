import unittest

from ai_trading_lab.candles import HOUR_MS, Candle
from ai_trading_lab.indicators import atr, ema, relative_volume, rsi, swing_points


def candle(i, o, h, l, c, v=1.0):
    return Candle(i * HOUR_MS, (i + 1) * HOUR_MS - 1, o, h, l, c, v)


class IndicatorsTest(unittest.TestCase):
    def test_ema_of_constant_series_is_constant(self):
        self.assertEqual(ema([5.0] * 30, 20)[-1], 5.0)

    def test_rsi_extremes(self):
        self.assertEqual(rsi([float(i) for i in range(30)]), 100.0)
        self.assertAlmostEqual(rsi([float(30 - i) for i in range(30)]), 0.0)

    def test_atr_of_constant_range(self):
        candles = [candle(i, 10, 11, 9, 10) for i in range(30)]
        self.assertAlmostEqual(atr(candles), 2.0)

    def test_relative_volume(self):
        candles = [candle(i, 1, 1, 1, 1, v=10) for i in range(20)] + [candle(20, 1, 1, 1, 1, v=30)]
        self.assertAlmostEqual(relative_volume(candles), 3.0)

    def test_swing_points_find_isolated_peak_and_trough(self):
        highs = [10, 11, 12, 20, 12, 11, 10, 9, 8, 2, 8, 9, 10]
        candles = [candle(i, h, h, h, h) for i, h in enumerate(highs)]
        swing_highs, swing_lows = swing_points(candles)
        self.assertIn((3 - len(highs), 20), swing_highs)
        self.assertIn((9 - len(highs), 2), swing_lows)


if __name__ == "__main__":
    unittest.main()
