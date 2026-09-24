import unittest
from datetime import datetime, timezone

import numpy as np

from ai_trading_lab.backtest import Bars, lookahead_violations
from ai_trading_lab.sentiment import parse_rwa_tvl, parse_stablecoin_supply
from ai_trading_lab.sentiment_history import DAY_MS, growth_series, parse_stablecoin_history
from ai_trading_lab.strategies import channel_trend, channel_trend_filtered
from tests.synthetic import random_walk

D0 = 1_790_208_000_000  # 2026-09-24T00:00Z
BASE = {"entry_lookback": 20, "exit_lookback": 10, "stop_atr": 2.0}
NOW = datetime(2026, 9, 24, 7, 30, tzinfo=timezone.utc)


def stable_payload(values, start=D0):
    return [{"date": str((start + i * DAY_MS) // 1000), "totalCirculatingUSD": {"peggedUSD": v}}
            for i, v in enumerate(values)]


class DefiLlamaParseTest(unittest.TestCase):
    def test_stablecoin_supply_keeps_last_days(self):
        obs = parse_stablecoin_supply(stable_payload([100.0, 101.0, 102.5]), last=2)
        self.assertEqual([o["value"] for o in obs], ["101.0", "102.5"])
        self.assertEqual(obs[-1]["observed_at"], "2026-09-26T00:00:00+00:00")
        self.assertEqual((obs[0]["source"], obs[0]["metric"], obs[0]["symbol"]),
                         ("defillama", "stablecoin_supply_usd", None))

    def test_rwa_tvl_sums_only_rwa_category_once_per_day(self):
        protocols = [{"category": "RWA", "tvl": 1.5e9}, {"category": "RWA", "tvl": None},
                     {"category": "Dexs", "tvl": 9e9}, {"category": "RWA", "tvl": 2.5e9}]
        [obs] = parse_rwa_tvl(protocols, NOW)
        self.assertEqual(float(obs["value"]), 4.0e9)
        self.assertEqual(obs["metric"], "rwa_tvl_usd")
        self.assertEqual(obs["observed_at"], "2026-09-24T00:00:00+00:00")


class GrowthFeatureTest(unittest.TestCase):
    def test_history_by_utc_day(self):
        series = parse_stablecoin_history(stable_payload([100.0, 110.0]))
        self.assertEqual(series, {D0: 100.0, D0 + DAY_MS: 110.0})

    def test_growth_uses_only_the_previous_day(self):
        # La vela del día D cierra a las 00:00 de D+1: se usa el dato fechado D-1 frente a D-1-30.
        series = {D0 + k * DAY_MS: 100.0 + k for k in range(40)}
        growth = growth_series(series, window=30, lag_days=1)
        day = D0 + 35 * DAY_MS
        self.assertAlmostEqual(growth[day], (100.0 + 34) / (100.0 + 4) - 1)
        self.assertNotIn(D0 + 30 * DAY_MS, growth)  # sin el dato de hace 31 días no hay crecimiento


class MinValueFilterTest(unittest.TestCase):
    def setUp(self):
        self.bars = random_walk(3000, np.random.default_rng(4))

    def with_feature(self, values):
        b = self.bars
        return Bars(b.open_time, b.open, b.high, b.low, b.close, b.volume, features={"stablecoin_growth_30d": values})

    def test_blocks_entries_when_liquidity_is_not_growing(self):
        values = np.where(np.arange(len(self.bars)) % 3 == 0, -0.02, 0.03)
        values[:400] = np.nan
        b = self.with_feature(values)
        base = channel_trend(b, BASE)
        f = channel_trend_filtered(b, {**BASE, "filter": "stablecoin_growth_30d", "min_value": 0.0})
        self.assertTrue(base.entries.any())
        np.testing.assert_array_equal(f.entries, base.entries & (values > 0.0))
        self.assertFalse(f.entries[:400].any())
        np.testing.assert_array_equal(f.exits, base.exits)

    def test_none_is_the_base_strategy(self):
        b = self.with_feature(np.zeros(len(self.bars)))
        f = channel_trend_filtered(b, {**BASE, "filter": "stablecoin_growth_30d", "min_value": None})
        np.testing.assert_array_equal(f.entries, channel_trend(b, BASE).entries)

    def test_min_filter_is_causal(self):
        b = self.with_feature(np.random.default_rng(5).normal(0.01, 0.02, len(self.bars)))
        p = {**BASE, "filter": "stablecoin_growth_30d", "min_value": 0.0}
        self.assertEqual(lookahead_violations(channel_trend_filtered, b, p, range(100, 3000, 101)), [])


if __name__ == "__main__":
    unittest.main()
