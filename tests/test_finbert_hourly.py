import json
import subprocess
import sys
import unittest
from datetime import timedelta

from dashboard.hourly import build_hourly
from tests.test_orquestador import H, record
from tools import finbert_score as fb
from tools import orquestador as o


class FinbertAggregateTest(unittest.TestCase):
    def test_tone_per_symbol_and_extremes(self):
        items = [{"titulo": "BTC ETF inflows hit record", "simbolos": ["BTCUSDT"]},
                 {"titulo": "Exchange hacked, funds drained", "simbolos": ["BTCUSDT", "ETHUSDT"]},
                 {"titulo": "Markets flat", "simbolos": []}]
        labels = ["positive", "negative", "neutral"]
        probs = [[0.9, 0.05, 0.05], [0.02, 0.95, 0.03], [0.1, 0.1, 0.8]]
        out = fb.aggregate(items, probs, labels)
        self.assertEqual(out["n"], 3)
        self.assertAlmostEqual(out["mercado"], round((0.85 - 0.93 + 0) / 3, 4))
        self.assertAlmostEqual(out["por_activo"]["BTCUSDT"]["tono"], round((0.85 - 0.93) / 2, 4))
        self.assertEqual(out["por_activo"]["ETHUSDT"]["n"], 1)
        self.assertEqual(out["mas_negativo"][0]["titulo"], "Exchange hacked, funds drained")
        self.assertEqual(out["mas_positivo"][0]["titulo"], "BTC ETF inflows hit record")
        self.assertEqual((out["positivos"], out["negativos"]), (1, 1))

    def test_label_order_comes_from_the_model(self):
        out = fb.aggregate([{"titulo": "x", "simbolos": []}], [[0.1, 0.7, 0.2]], ["neutral", "positive", "negative"])
        self.assertAlmostEqual(out["mercado"], 0.5)

    def test_no_headlines_never_loads_the_model(self):
        self.assertEqual(fb.score([])["n"], 0)


class ProcessStageTest(unittest.TestCase):
    def config(self, python=sys.executable, need=None):
        return {"contenedores": [{"nombre": "finbert", "python": python, "modulo": "tools.finbert_score", "activo": True,
                                  "memoria_min_gb": need, "timeout": 60}]}

    def test_context_goes_through_stdin_to_the_other_python(self):
        seen = {}

        def run(cmd, **kwargs):
            seen["cmd"], seen["input"], seen["cwd"] = cmd, kwargs["input"], kwargs["cwd"]
            return subprocess.CompletedProcess(cmd, 0, 'cargando\n{"mercado": -0.2, "n": 2}', "")
        ctx = {"titulares": [{"titulo": "a", "simbolos": []}] * 2}
        out = o.stage_containers(self.config(), ctx, lambda: 100, run=run)
        self.assertEqual(out["finbert"], {"mercado": -0.2, "n": 2})
        self.assertEqual(seen["cmd"], [sys.executable, "-m", "tools.finbert_score"])
        self.assertEqual(len(json.loads(seen["input"])["titulares"]), 2)
        self.assertEqual(seen["cwd"], o.ROOT)

    def test_low_memory_skips_without_running(self):
        calls = []
        out = o.stage_containers(self.config(need=1.2), {}, lambda: 100, run=lambda *a, **k: calls.append(a), free=lambda: 0.6)
        self.assertIn("0.6 GB < 1.2 GB", out["finbert"]["error"])
        self.assertEqual(calls, [])

    def test_missing_environment_is_reported(self):
        out = o.stage_containers(self.config(python=r"C:\no\existe\python.exe"), {}, lambda: 100, run=None)
        self.assertEqual(out["finbert"]["error"], "no está instalado su entorno")

    def test_failed_process_does_not_stop_the_note(self):
        run = lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "boom")  # noqa: E731
        error = o.stage_containers(self.config(), {}, lambda: 100, run=run)["finbert"]["error"]
        self.assertTrue(error.startswith("RuntimeError: tools.finbert_score: código 1"))
        self.assertIn("boom", error)  # la causa real llega a la nota


class HourlyTest(unittest.TestCase):
    def test_latest_note_and_last_evaluated_hour(self):
        first = record(H, action="BUY_CANDIDATE", sym="BTCUSDT")
        later = record(H + timedelta(hours=4), btc_price=120)
        later["contenedores"] = {"finbert": {"n": 5, "mercado": 0.1}}
        out = build_hourly([first, later], {"cargado": True})
        self.assertEqual(out["nota"]["nombre"], later["nombre"])
        self.assertEqual(out["nota"]["finbert"]["n"], 5)
        self.assertEqual(out["evaluada"]["nombre"], first["nombre"])
        self.assertEqual(out["evaluada"]["resultado"], "exitosa")
        self.assertTrue(out["timesfm_servicio"]["cargado"])

    def test_down_service_and_no_notes(self):
        out = build_hourly([], None)
        self.assertIsNone(out["nota"])
        self.assertFalse(out["timesfm_servicio"]["cargado"])


if __name__ == "__main__":
    unittest.main()
