import tempfile
import unittest
from pathlib import Path

from tools import predicciones as p

NINO_TEXT = """YR   MON  NINO1+2  ANOM   NINO3    ANOM   NINO4    ANOM NINO3.4    ANOM
2026    5   24.10   0.50   27.50   0.70   29.10   0.40   28.40   0.90
2026    6   23.20   0.80   27.60   1.20   29.30   0.60   28.70   1.44
"""


class ParseTest(unittest.TestCase):
    def test_nino_takes_the_nino34_anomaly(self):
        self.assertEqual(p.parse_nino(NINO_TEXT), [(2026, 5, 0.9), (2026, 6, 1.44)])

    def test_power_converts_mm_per_day_and_skips_annual_and_gaps(self):
        payload = {"properties": {"parameter": {"PRECTOTCORR": {"202601": 2.0, "202602": -999, "202613": 3.0}}}}
        self.assertEqual(p.parse_power(payload), {(2026, 1): 62.0})

    def test_strong_nino_composite_and_correlation(self):
        nino = [(y, m, 2.0 if y % 2 else -1.0) for y in range(2000, 2010) for m in range(1, 13)]
        rain = {(y, m): (150.0 if y % 2 else 100.0) for y in range(2000, 2010) for m in range(1, 13)}
        stats = p.enso_sierra_stats(nino, {"X": rain})["X"]
        self.assertGreater(stats["corr_by_lag_months"][0], 0.9)
        self.assertEqual(stats["strong_nino_rain_change_by_season"]["jun-ago"]["rain_change_pct"], 20.0)


class StoreTest(unittest.TestCase):
    def test_requests_and_results_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = p.DATA
            p.DATA = Path(tmp)
            try:
                item = p.add_request("  ¿Cómo estará   el clima en Quito?  ")
                self.assertEqual(item["question"], "¿Cómo estará el clima en Quito?")
                with self.assertRaises(ValueError):
                    p.add_request("corta")
                self.assertEqual(p.load_all()["requests"][0]["status"], "pendiente")
                p.save_result({"id": item["id"], "question": item["question"], "summary": ["x"], "caveats": [],
                               "series": [{"name": "s", "history": []}], "sources": [{"name": "n", "url": "https://x.org"}]})
                self.assertEqual(p.load_all()["requests"][0]["status"], "respondida")
            finally:
                p.DATA = old

    def test_invalid_results_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                p.save_result({"id": "a"}, base=tmp)
            with self.assertRaises(ValueError):
                p.save_result({"id": "a", "question": "q", "summary": [], "caveats": [], "series": [{"name": "s", "history": []}],
                               "sources": [{"name": "n", "url": "javascript:alert(1)"}]}, base=tmp)


if __name__ == "__main__":
    unittest.main()
