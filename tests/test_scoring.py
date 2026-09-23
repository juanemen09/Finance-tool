import unittest

from ai_trading_lab.candles import HOUR_MS, Candle
from ai_trading_lab.scoring import score_buy, score_no_trade

FAR_FUTURE = 10**15


def bars(*ohlc):
    return [Candle(i * HOUR_MS, (i + 1) * HOUR_MS - 1, o, h, l, c, 1.0) for i, (o, h, l, c) in enumerate(ohlc)]


# Zona 99-100, invalidación 95 (riesgo 5 desde 100), target 110 (+2R).
LEVELS = dict(entry_low=99, entry_high=100, invalidation=95, target=110)


class ScoreBuyTest(unittest.TestCase):
    def test_target_hit_is_plus_two_r(self):
        s = score_buy(**LEVELS, candles=bars((102, 103, 99.5, 101), (101, 111, 100, 110)), valid_until_ms=FAR_FUTURE)
        self.assertEqual(s.outcome, "TARGET_HIT")
        self.assertEqual(s.fill_price, 100)
        self.assertEqual(s.r_multiple, 2.0)
        # Comisiones: (100 + 110) * 0.001 / 5 = 0.042 R
        self.assertAlmostEqual(s.r_multiple_after_fees, 1.958)

    def test_stop_hit_is_minus_one_r(self):
        s = score_buy(**LEVELS, candles=bars((102, 103, 99.5, 101), (101, 101, 94, 95)), valid_until_ms=FAR_FUTURE)
        self.assertEqual(s.outcome, "STOP_HIT")
        self.assertEqual(s.r_multiple, -1.0)
        self.assertLess(s.r_multiple_after_fees, -1.0)

    def test_stop_wins_when_both_touched_in_same_candle(self):
        s = score_buy(**LEVELS, candles=bars((100, 100, 99, 100), (100, 112, 94, 105)), valid_until_ms=FAR_FUTURE)
        self.assertEqual(s.outcome, "STOP_HIT")

    def test_target_ignored_in_fill_candle(self):
        # La vela de llenado toca 111, pero no sabemos si fue antes o después de llenar.
        s = score_buy(**LEVELS, candles=bars((105, 111, 99.5, 108), (108, 109, 104, 106)), valid_until_ms=FAR_FUTURE)
        self.assertEqual(s.outcome, "OPEN_AT_HORIZON")
        self.assertEqual(s.exit_price, 106)

    def test_fill_at_open_when_gapping_into_zone(self):
        s = score_buy(**LEVELS, candles=bars((99.5, 100, 99.2, 99.8), (99.8, 110, 99.6, 109)), valid_until_ms=FAR_FUTURE)
        self.assertEqual(s.fill_price, 99.5)
        self.assertEqual(s.outcome, "TARGET_HIT")

    def test_not_filled_when_price_never_reaches_zone(self):
        s = score_buy(**LEVELS, candles=bars((105, 108, 101, 107), (107, 115, 106, 114)), valid_until_ms=FAR_FUTURE)
        self.assertEqual(s.outcome, "NOT_FILLED")

    def test_not_filled_when_zone_touched_after_expiry(self):
        s = score_buy(**LEVELS, candles=bars((105, 108, 101, 107), (107, 107, 99, 100)), valid_until_ms=HOUR_MS)
        self.assertEqual(s.outcome, "NOT_FILLED")

    def test_mfe_and_mae_measured_from_fill(self):
        s = score_buy(**LEVELS, candles=bars((100, 100, 99, 100), (100, 104, 97, 103)), valid_until_ms=FAR_FUTURE)
        self.assertEqual(s.mfe_pct, 4.0)
        self.assertEqual(s.mae_pct, -3.0)

    def test_rejects_incoherent_levels(self):
        with self.assertRaises(ValueError):
            score_buy(entry_low=99, entry_high=100, invalidation=99.5, target=110, candles=[], valid_until_ms=0)


class ScoreNoTradeTest(unittest.TestCase):
    def test_reports_moves_from_reference(self):
        s = score_no_trade(100, bars((100, 105, 98, 102), (102, 103, 96, 97)))
        self.assertEqual(s.outcome, "NO_TRADE")
        self.assertEqual(s.details["max_up_pct"], 5.0)
        self.assertEqual(s.details["max_down_pct"], -4.0)
        self.assertEqual(s.details["close_change_pct"], -3.0)


if __name__ == "__main__":
    unittest.main()
