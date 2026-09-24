import unittest

import numpy as np

from tools.ingest_sources import build_query, parse_feed
from tools.run_hard_test import forward_review, resolve
from ai_trading_lab.backtest import Costs, Signals
from tests.synthetic import START_MS, planted_edge, random_walk
from tests.test_validation import rebound_after_drop

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2608.01234v2</id>
    <published>2026-08-22T10:06:04Z</published>
    <title>Short-horizon mean reversion
      in cryptocurrency markets</title>
    <summary>We study   reversals.</summary>
    <author><name>A. Author</name></author>
    <author><name>B. Author</name></author>
  </entry>
</feed>"""


class IngestTest(unittest.TestCase):
    def test_parses_arxiv_entry_without_version(self):
        [p] = parse_feed(FEED)
        self.assertEqual(p["source_key"], "arxiv:2608.01234")
        self.assertEqual(p["url"], "https://arxiv.org/abs/2608.01234")
        self.assertEqual(p["title"], "Short-horizon mean reversion in cryptocurrency markets")
        self.assertEqual(p["authors"], ["A. Author", "B. Author"])
        self.assertEqual(p["published_at"], "2026-08-22")

    def test_query_restricts_to_quant_finance_categories(self):
        q = build_query(["bitcoin"])
        self.assertIn("cat:q-fin.TR", q)
        self.assertIn('abs:"bitcoin"', q)


class ResolveTest(unittest.TestCase):
    def test_rejects_implementation_outside_catalog(self):
        with self.assertRaises(SystemExit):
            resolve("os:system")

    def test_accepts_catalog_strategy(self):
        self.assertTrue(callable(resolve("ai_trading_lab.strategies:breakout")))


class ForwardReviewTest(unittest.TestCase):
    PARAMS = {"drop": 0.025, "hold": 5}

    def test_insufficient_trades_gives_no_verdict(self):
        data = {"A": random_walk(2000, np.random.default_rng(0))}
        since = int(data["A"].open_time[-50])
        verdict, summary = forward_review(rebound_after_drop, self.PARAMS, data, since, Costs(), 0.0)
        self.assertIsNone(verdict)

    def test_pass_with_real_edge_and_fail_without(self):
        edge = {"A": planted_edge(8000, np.random.default_rng(3))}
        noise = {"A": random_walk(8000, np.random.default_rng(3))}
        noise_params = {"drop": 0.012, "hold": 5}  # umbral bajo para que el ruido genere operaciones
        self.assertEqual(forward_review(rebound_after_drop, self.PARAMS, edge, START_MS, Costs(), 0.0)[0], "PASS")
        self.assertEqual(forward_review(rebound_after_drop, noise_params, noise, START_MS, Costs(), 0.0)[0], "FAIL")


if __name__ == "__main__":
    unittest.main()
