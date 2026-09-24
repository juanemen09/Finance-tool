import io
import json
import unittest
import zipfile

import numpy as np

from ai_trading_lab.backtest import Bars, Costs, lookahead_violations, run
from ai_trading_lab.sentiment_history import (
    DAY_MS, align_daily, attach_daily_features, daily_funding, parse_fear_greed_history, parse_funding_zip,
)
from ai_trading_lab.strategies import CATALOG, channel_trend, channel_trend_filtered
from ai_trading_lab.validation import incremental_test
from tests.synthetic import START_MS, random_walk

D0 = 1_790_208_000_000  # 2026-09-24T00:00Z
BASE = {"entry_lookback": 20, "exit_lookback": 10, "stop_atr": 2.0}


def zipped_csv(text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.csv", text)
    return buffer.getvalue()


def with_feature(bars, name, values):
    return Bars(bars.open_time, bars.open, bars.high, bars.low, bars.close, bars.volume, features={name: values})


class HistoryTest(unittest.TestCase):
    def test_fear_greed_history_by_utc_day(self):
        payload = {"data": [{"value": "71", "timestamp": str(D0 // 1000)},
                            {"value": "20", "timestamp": str((D0 - DAY_MS) // 1000)}]}
        self.assertEqual(parse_fear_greed_history(payload), {D0: 71.0, D0 - DAY_MS: 20.0})

    def test_funding_zip_rows_and_daily_sum(self):
        # Intervalos de 8h y de 4h: la suma diaria es comparable entre pares (coste por día).
        raw = zipped_csv("calc_time,funding_interval_hours,last_funding_rate\n"
                         f"{D0 + 1},8,0.0001\n{D0 + 8 * 3600_000},8,0.0002\n{D0 + 16 * 3600_000},4,0.0003\n"
                         f"{D0 + DAY_MS + 1},8,0.0005\n")
        events = parse_funding_zip(raw)
        self.assertEqual(events[0], (D0 + 1, 0.0001))
        daily = daily_funding(events)
        self.assertAlmostEqual(daily[D0], 0.0006)
        self.assertAlmostEqual(daily[D0 + DAY_MS], 0.0005)  # 00:00:00.001 del día siguiente es de ese día

    def test_align_daily_marks_missing_days(self):
        out = align_daily(np.array([D0 - DAY_MS, D0, D0 + DAY_MS]), {D0: 5.0})
        self.assertTrue(np.isnan(out[0]))
        self.assertEqual(out[1], 5.0)
        self.assertTrue(np.isnan(out[2]))


class AttachTest(unittest.TestCase):
    def test_bars_start_when_every_series_exists(self):
        days = np.array([D0 + k * DAY_MS for k in range(6)], dtype=np.int64)
        ones = np.ones(6)
        b = Bars(days, ones, ones, ones, ones, ones)
        out = attach_daily_features(b, {"fear_greed": {int(d): 50.0 for d in days[1:]},
                                        "funding": {int(d): 1e-4 for d in days[3:] if d != days[4]}})
        self.assertEqual(list(out.open_time), list(days[3:]))
        self.assertTrue(np.isnan(out.features["funding"][1]))  # hueco posterior: se conserva como nan
        self.assertEqual(out.features["fear_greed"][0], 50.0)


class FilteredStrategyTest(unittest.TestCase):
    def setUp(self):
        self.bars = random_walk(3000, np.random.default_rng(1))

    def test_slice_keeps_features(self):
        b = with_feature(self.bars, "fear_greed", np.arange(len(self.bars), dtype=float))
        part = b.slice(10, 20)
        self.assertEqual(list(part.features["fear_greed"]), list(range(10, 20)))

    def test_no_limit_equals_base_strategy(self):
        b = with_feature(self.bars, "fear_greed", np.full(len(self.bars), 99.0))
        base = channel_trend(b, BASE)
        same = channel_trend_filtered(b, {**BASE, "filter": "fear_greed", "max_value": None})
        np.testing.assert_array_equal(base.entries, same.entries)
        np.testing.assert_array_equal(base.exits, same.exits)

    def test_blocks_entries_at_or_above_limit_and_when_missing(self):
        values = np.where(np.arange(len(self.bars)) % 2 == 0, 90.0, 10.0)
        values[:500] = np.nan
        b = with_feature(self.bars, "fear_greed", values)
        base = channel_trend(b, BASE)
        filtered = channel_trend_filtered(b, {**BASE, "filter": "fear_greed", "max_value": 80})
        self.assertTrue(base.entries.any())
        self.assertFalse(filtered.entries[:500].any())
        self.assertFalse((filtered.entries & (values >= 80)).any())
        kept = base.entries & (values < 80)
        np.testing.assert_array_equal(filtered.entries, kept)
        self.assertTrue(np.isnan(filtered.stop[~filtered.entries]).all())
        np.testing.assert_array_equal(filtered.exits, base.exits)  # salir nunca se filtra

    def test_filter_is_causal(self):
        b = with_feature(self.bars, "funding", np.random.default_rng(2).normal(0, 1e-4, len(self.bars)))
        p = {**BASE, "filter": "funding", "max_value": 0.0}
        self.assertEqual(lookahead_violations(channel_trend_filtered, b, p, range(100, 3000, 97)), [])

    def test_missing_feature_fails_loudly(self):
        with self.assertRaises(KeyError):
            channel_trend_filtered(self.bars, {**BASE, "filter": "fear_greed", "max_value": 50})

    def test_catalog_entry(self):
        fn, grid = CATALOG["channel_trend_filtered"]
        self.assertIs(fn, channel_trend_filtered)
        self.assertTrue(all(p["filter"] in ("fear_greed", "funding") for p in grid))


class IncrementalCalibrationTest(unittest.TestCase):
    """El chequeo de "¿el filtro aporta?" debe aprobar un filtro que sabe algo y reprobar uno que no."""
    N, TRAIN, TEST, HOLD = 26_280, 8760, 2190, 4380  # 3 años de velas de 1h

    def setUp(self):
        rng = np.random.default_rng(11)
        self.raw = {"A": random_walk(self.N, rng), "B": random_walk(self.N, rng)}

    def _run(self, features, grid):
        data = {s: with_feature(b, "fear_greed", features[s]) for s, b in self.raw.items()}
        return incremental_test(channel_trend_filtered, grid, {**BASE, "filter": "fear_greed", "max_value": None},
                                data, costs=Costs(), holdout_bars=self.HOLD, train_bars=self.TRAIN,
                                test_bars=self.TEST, null_sims=40, seed=0)

    def test_oracle_filter_passes(self):
        features = {}
        for s, b in self.raw.items():
            losers = [t.signal_idx for t in run(b, channel_trend(b, BASE)) if t.net_return < 0]
            f = np.zeros(len(b))
            f[losers] = 100.0
            features[s] = f
        result = self._run(features, [{**BASE, "filter": "fear_greed", "max_value": v} for v in (50,)])
        self.assertGreater(result["mean_diff"], 0)
        self.assertGreaterEqual(result["null_percentile"], 95)
        self.assertGreater(result["blocked_signals"], 10)

    def test_random_filters_are_rejected_at_the_nominal_rate(self):
        # En un paseo aleatorio la base pierde por costes y bloquear al azar "mejora" (mean_diff > 0): la
        # comparación contra filtros desplazados debe dejar el percentil repartido al azar, no pegado a 100.
        # Con una sola semilla habría un 5 % de fallos esperables; se calibra con varias.
        percentiles = []
        for seed in range(8):
            rng = np.random.default_rng(100 + seed)
            b = random_walk(self.N, rng)
            data = {"A": with_feature(b, "fear_greed", rng.uniform(0, 100, len(b)))}
            result = incremental_test(channel_trend_filtered,
                                      [{**BASE, "filter": "fear_greed", "max_value": v} for v in (30, 50, 70)],
                                      {**BASE, "filter": "fear_greed", "max_value": None}, data, costs=Costs(),
                                      holdout_bars=self.HOLD, train_bars=self.TRAIN, test_bars=self.TEST,
                                      null_sims=20, seed=seed)
            percentiles.append(result["null_percentile"])
        self.assertLessEqual(sum(p >= 95 for p in percentiles), 1, percentiles)
        self.assertTrue(20 <= np.median(percentiles) <= 80, percentiles)

    def test_holdout_is_never_touched(self):
        # Si el filtro solo cambiara la reserva, el resultado del desarrollo no debe moverse.
        base_f = {s: np.zeros(len(b)) for s, b in self.raw.items()}
        tail_f = {s: np.r_[np.zeros(len(b) - self.HOLD), np.full(self.HOLD, 100.0)] for s, b in self.raw.items()}
        grid = [{**BASE, "filter": "fear_greed", "max_value": v} for v in (50,)]
        a, b = self._run(base_f, grid), self._run(tail_f, grid)
        self.assertEqual(a["mean_diff"], b["mean_diff"])
        self.assertEqual(json.dumps(a, sort_keys=True, default=float), json.dumps(b, sort_keys=True, default=float))


if __name__ == "__main__":
    unittest.main()
