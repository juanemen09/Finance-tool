import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_trading_lab.candles import Candle
from tools import orquestador as o

H = datetime(2026, 9, 30, 17, tzinfo=timezone.utc)


def record(hour, btc_price=100.0, ret=1.0, rsi=50.0, fg=60.0, tone=0.1, action=None, sym=None, band=(90.0, 110.0)):
    return {"hora": hour.isoformat(), "nombre": o.note_name(hour), "ciclo": f"{hour:%Y-%m-%dT%H}Z",
            "mercado": {"BTCUSDT": {"precio": btc_price, "ret_24h_pct": ret, "rsi14": rsi, "atr_pct": 1.0}},
            "sentimiento": {"fear_greed": fg, "tono_mercado": tone},
            "timesfm": {"BTCUSDT": {"steps": [{"h": 4, "p10": band[0], "p50": 100.0, "p90": band[1]}]}},
            "agentes": {"claude": {"accion": action, "simbolo": sym}} if action else {}}


class IndicatorsTest(unittest.TestCase):
    def test_rsi_extremes_and_indicators(self):
        self.assertEqual(o.rsi(list(range(1, 30))), 100.0)
        self.assertLess(o.rsi(list(range(30, 1, -1))), 1)
        candles = [Candle(i, i + 1, 100 + i, 101 + i, 99 + i, 100 + i, 10) for i in range(200)]
        ind = o.indicators(candles)
        self.assertAlmostEqual(ind["ret_1h_pct"], (299 / 298 - 1) * 100)
        self.assertTrue(ind["sobre_ema50"])


class GuardTest(unittest.TestCase):
    def test_tight_book_passes(self):
        book = {"bids": [["99.99", "10"]], "asks": [["100.01", "10"]]}
        g = o.execution_guard(book)
        self.assertFalse(g["abortar"])
        self.assertAlmostEqual(g["spread_pct"], 0.02)
        self.assertAlmostEqual(g["deslizamiento_compra_pct"], 0.0)

    def test_wide_spread_aborts(self):
        g = o.execution_guard({"bids": [["99.5", "10"]], "asks": [["100.5", "10"]]})
        self.assertTrue(g["abortar"])
        self.assertIn("spread", g["motivo"])

    def test_thin_book_slippage_aborts(self):
        # 7 USDT: 1 USDT al mejor precio y el resto un 1 % más caro
        g = o.execution_guard({"bids": [["100", "1"]], "asks": [["100", "0.01"], ["101", "1"]]})
        self.assertTrue(g["abortar"])
        self.assertIn("deslizamiento de compra", g["motivo"])

    def test_empty_book_aborts(self):
        self.assertTrue(o.execution_guard({"bids": [], "asks": []})["abortar"])


class MemoryTest(unittest.TestCase):
    def test_nearest_past_regime_excluding_last_day(self):
        history = [record(H - timedelta(hours=48 + i), ret=r, rsi=s) for i, (r, s) in enumerate([(5, 70), (-5, 30), (0, 50), (4.8, 69)])]
        history.append(record(H - timedelta(hours=2), ret=5, rsi=70))  # igual, pero demasiado reciente
        similar = o.similar_hours(history, record(H, ret=5, rsi=70), k=2)
        names = [s["nombre"] for s in similar]
        self.assertEqual(names[0], o.note_name(H - timedelta(hours=48)))
        self.assertNotIn(o.note_name(H - timedelta(hours=2)), names)


class EvaluateTest(unittest.TestCase):
    def test_pending_until_four_hours_later(self):
        self.assertEqual(o.evaluate(record(H), None)["resultado"], "pendiente")

    def test_anomaly_and_thesis_outcome(self):
        out = o.evaluate(record(H, action="BUY_CANDIDATE", sym="BTCUSDT"), record(H + timedelta(hours=4), btc_price=120))
        self.assertEqual(out["resultado"], "exitosa")
        self.assertEqual(sorted(out["tags"]), ["anomalia", "tesis-exitosa"])
        out = o.evaluate(record(H, action="BUY_CANDIDATE", sym="BTCUSDT"), record(H + timedelta(hours=4), btc_price=95))
        self.assertEqual(out["tags"], ["tesis-fallida"])


class NoteTest(unittest.TestCase):
    def test_frontmatter_is_typed_and_links_are_there(self):
        r = record(H)
        outcome = {"resultado": "pendiente", "tags": ["anomalia"], "detalle": {}}
        text = o.render(r, o.note_name(H - timedelta(hours=1)), [{"nombre": "2026-08-15_10H00", "distancia": 0.3}], outcome)
        head = text.split("---\n")[1]
        self.assertIn("btc_precio: 100.0", head)
        self.assertIn("fear_greed: 60.0", head)
        self.assertIn('ciclo: "2026-09-30T17Z"', head)
        self.assertIn('tags: ["hora", "anomalia"]', head)
        self.assertIn("[[2026-09-30_16H00]]", text)
        self.assertIn("[[2026-08-15_10H00]]", text)

    def test_user_text_survives_and_frontmatter_is_replaced(self):
        outcome = {"resultado": "pendiente", "tags": [], "detalle": {}}
        first = o.render(record(H), None, [], outcome)
        edited = first.replace(o.START, "Mi observación\n" + o.START)
        second = o.render(record(H, btc_price=105.0), None, [], outcome, edited)
        self.assertIn("Mi observación", second)
        self.assertEqual(second.count("tipo: \"hora\""), 1)
        self.assertIn("btc_precio: 105.0", second)


class ContainerTest(unittest.TestCase):
    def test_ephemeral_container_command(self):
        seen = {}

        def run(cmd, **kwargs):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, 'log\n{"score": 0.4}', "")
        self.assertEqual(o.run_container("img:local", ["x"], "2g", run=run), {"score": 0.4})
        self.assertEqual(seen["cmd"][:8], ["docker", "run", "--rm", "--memory", "2g", "--cpus", "2", "--network"])

    def test_inactive_stages_never_run(self):
        calls = []
        cfg = {"contenedores": [{"nombre": "a", "imagen": "i", "activo": False}]}
        self.assertEqual(o.stage_containers(cfg, {}, lambda: 100, run=lambda *a, **k: calls.append(a)), {})
        self.assertEqual(calls, [])


class ServiceTest(unittest.TestCase):
    def test_hourly_forecast_from_service_quantiles(self):
        from tools.tsfm_hourly import forecast_all
        candles = [Candle(i * 3_600_000, (i + 1) * 3_600_000 - 1, 100, 101, 99, 100.0, 1) for i in range(30)]
        seen = []

        def predict(log_closes, horizon):
            seen.append((len(log_closes), horizon))
            return [[log_closes[-1] + (q - 0.5) / 10 for q in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)]] * horizon
        out = forecast_all(predict, fetch=lambda *a, **k: candles)
        self.assertEqual(seen[0], (30, 4))
        step = out["BTCUSDT"]["steps"][3]
        self.assertAlmostEqual(step["p50"], 100.0)
        self.assertLess(step["p10"], step["p50"])
        self.assertGreater(step["p90"], step["p50"])

    def test_client_reports_down_service(self):
        from tools import tsfm_client
        self.assertIsNone(tsfm_client.status(url="http://127.0.0.1:9"))
        self.assertFalse(tsfm_client.ready(url="http://127.0.0.1:9"))


class ObsidianFallbackTest(unittest.TestCase):
    def test_without_key_writes_the_file_inside_its_folder(self):
        with tempfile.TemporaryDirectory() as vault:
            ob = o.Obsidian(vault, "https://127.0.0.1:1", "")
            self.assertEqual(ob.write("Horas/x.md", "hola"), "archivo")
            self.assertEqual(ob.read("Horas/x.md"), "hola")
            with self.assertRaises(ValueError):
                ob.write("../fuera.md", "no")


if __name__ == "__main__":
    unittest.main()
