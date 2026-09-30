import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from dashboard.config import load_env
from dashboard.health import agent_health
from dashboard.market import MarketError, candles_payload, liquidity_payload, radar_row, validate_candles_request
from dashboard.queries import build_state, equity_curve, next_daily_close, to_jsonable
from dashboard.server import make_server

NOW = datetime(2026, 9, 24, 6, 30, tzinfo=timezone.utc)


def fake_rows(sql):
    """Respuestas mínimas para cada consulta, reconocidas por una palabra clave del SQL."""
    if "v_latest_portfolio" in sql:
        return [{"balances": [{"asset": "USDT", "free": "20.0", "locked": "0"}], "open_orders": [],
                 "observed_at": NOW}]
    if "distinct on (agent_id)" in sql:
        return [{"agent_id": "claude", "created_at": datetime(2026, 9, 24, 6, 2, tzinfo=timezone.utc),
                 "proposed_action": "DO_NOTHING", "cycle_id": "2026-09-24T06Z"}]
    if "max(at)" in sql:
        return []
    if "v_research_latest" in sql:
        return [{"kind": "13F_BOOK", "as_of": NOW.date(), "title": "Libro 13F", "body": "b",
                 "data": {"book": []}, "created_at": NOW}]
    if "select observed_at, balances from portfolio_snapshots" in sql:
        return [{"observed_at": NOW, "balances": [{"asset": "USDT", "free": "20.0", "locked": "0"}]}]
    return []


class ConfigTest(unittest.TestCase):
    def test_env_parser_ignores_comments_and_quotes(self):
        path = Path(self.id().replace(".", "_") + ".env")
        path.write_text('# comentario\nDASHBOARD_DATABASE_URL="postgresql://u:p@h:5432/db"\nOTRA = valor \n\n',
                        encoding="utf-8")
        try:
            env = load_env(path)
        finally:
            path.unlink()
        self.assertEqual(env["DASHBOARD_DATABASE_URL"], "postgresql://u:p@h:5432/db")
        self.assertEqual(env["OTRA"], "valor")

    def test_missing_env_file_is_empty(self):
        self.assertEqual(load_env(Path("no-existe.env")), {})


class ShapingTest(unittest.TestCase):
    def test_json_conversion(self):
        out = to_jsonable({"a": Decimal("1.50"), "t": NOW, "l": [Decimal("2")]})
        self.assertEqual(out, {"a": 1.5, "t": "2026-09-24T06:30:00+00:00", "l": [2.0]})

    def test_next_daily_close(self):
        self.assertEqual(next_daily_close(NOW), datetime(2026, 9, 25, tzinfo=timezone.utc))

    @staticmethod
    def health_at(now, claude, chatgpt, pending=()):
        rows = [{"agent_id": "claude", "created_at": claude}, {"agent_id": "chatgpt", "created_at": chatgpt}]
        return {h["agent_id"]: h for h in agent_health(rows, list(pending), now)}

    def test_claude_is_late_after_75_minutes(self):
        health = self.health_at(NOW, datetime(2026, 9, 24, 5, 10, tzinfo=timezone.utc),
                                datetime(2026, 9, 24, 0, 20, tzinfo=timezone.utc))
        self.assertEqual(health["claude"]["state"], "atrasado")
        self.assertIn("80 min", health["claude"]["reason"])

    def test_codex_writing_once_a_day_is_not_late(self):
        # Codex escribe a las 00:20 UTC y no vuelve a escribir: seis horas después sigue al día.
        health = self.health_at(NOW, datetime(2026, 9, 24, 6, 2, tzinfo=timezone.utc),
                                datetime(2026, 9, 24, 0, 20, tzinfo=timezone.utc))
        self.assertEqual((health["claude"]["state"], health["chatgpt"]["state"]), ("ok", "ok"))
        self.assertEqual(health["chatgpt"]["minutes_since"], 370)

    def test_codex_missing_its_daily_cycle_is_late(self):
        health = self.health_at(NOW, datetime(2026, 9, 24, 6, 2, tzinfo=timezone.utc),
                                datetime(2026, 9, 23, 20, 15, tzinfo=timezone.utc))
        self.assertEqual(health["chatgpt"]["state"], "atrasado")
        self.assertIn("2026-09-24T00Z", health["chatgpt"]["reason"])

    def test_codex_window_still_open_before_0200_utc(self):
        # A las 01:30 UTC la ventana de hoy sigue abierta: basta con el análisis del día anterior.
        now = datetime(2026, 9, 24, 1, 30, tzinfo=timezone.utc)
        health = self.health_at(now, datetime(2026, 9, 24, 1, 6, tzinfo=timezone.utc),
                                datetime(2026, 9, 23, 0, 20, tzinfo=timezone.utc))
        self.assertEqual(health["chatgpt"]["state"], "ok")

    def test_unattended_mailbox_makes_codex_late(self):
        pending = [{"to_agent_id": "chatgpt", "n": 2, "oldest": datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)}]
        health = self.health_at(NOW, datetime(2026, 9, 24, 6, 2, tzinfo=timezone.utc),
                                datetime(2026, 9, 24, 0, 20, tzinfo=timezone.utc), pending)
        self.assertEqual(health["chatgpt"]["state"], "atrasado")
        self.assertIn("2 mensaje(s)", health["chatgpt"]["reason"])
        self.assertEqual(health["chatgpt"]["pending_messages"], 2)

    def test_recent_mailbox_is_fine(self):
        pending = [{"to_agent_id": "chatgpt", "n": 1, "oldest": datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)}]
        health = self.health_at(NOW, datetime(2026, 9, 24, 6, 2, tzinfo=timezone.utc),
                                datetime(2026, 9, 24, 0, 20, tzinfo=timezone.utc), pending)
        self.assertEqual(health["chatgpt"]["state"], "ok")

    def test_agent_without_rows_is_silent(self):
        health = {h["agent_id"]: h for h in agent_health([], [], NOW)}
        self.assertEqual(health["chatgpt"]["state"], "sin actividad")

    def test_equity_counts_usdt_and_flags_other_assets(self):
        rows = [{"observed_at": NOW, "balances": [{"asset": "USDT", "free": "12.5", "locked": "0.5"},
                                                  {"asset": "BTC", "free": "0.0001", "locked": "0"}]}]
        [point] = equity_curve(rows)
        self.assertEqual(point["usdt"], 13.0)
        self.assertEqual(point["other_assets"], ["BTC"])

    def test_state_has_every_panel_and_no_secrets(self):
        state = build_state(fake_rows, NOW)
        for key in ("now", "next_daily_close", "portfolio", "agents", "timeline", "strategies", "signals",
                    "proposals", "sentiment", "news", "research", "equity", "risk_limits", "open_events"):
            self.assertIn(key, state)
        self.assertNotIn("postgresql://", json.dumps(state))
        self.assertEqual(list(state["ai_thesis"]), ["13F_BOOK"], "la tesis IA llega indexada por tipo de informe")
        self.assertEqual(state["forecast"], {"latest": [], "skill": []}, "sin pronósticos, el panel recibe listas vacías")


class MarketTest(unittest.TestCase):
    def test_only_universe_symbols_and_known_intervals(self):
        self.assertEqual(validate_candles_request("BTCUSDT", "1d"), ("BTCUSDT", "1d"))
        for symbol, interval in [("DOGEUSDT", "1d"), ("BTCUSDT", "1m"), ("BTCUSDT'; drop", "1d")]:
            with self.assertRaises(MarketError):
                validate_candles_request(symbol, interval)

    def test_daily_payload_includes_channel_levels(self):
        from ai_trading_lab.candles import Candle
        day = 86_400_000
        candles = [Candle(i * day, (i + 1) * day - 1, 100 + i, 101 + i, 99 + i, 100.5 + i, 10) for i in range(30)]
        payload = candles_payload("BTCUSDT", "1d", candles)
        self.assertEqual(len(payload["candles"]), 30)
        self.assertIsNone(payload["channel"][19]["entry_level"])  # sin 20 velas previas no hay canal
        self.assertEqual(payload["channel"][25]["entry_level"], max(101 + i for i in range(5, 25)))
        self.assertEqual(payload["channel"][25]["exit_level"], min(99 + i for i in range(15, 25)))

    def test_radar_uses_closed_candles_for_levels_and_live_price(self):
        from ai_trading_lab.candles import Candle
        day = 86_400_000
        closed = [Candle(i * day, (i + 1) * day - 1, 100, 110 + i, 90 + i, 100 + i, 10) for i in range(25)]
        forming = Candle(25 * day, 26 * day - 1, 124, 200, 50, 130, 1)  # máximo y mínimo extremos a medio día
        row = radar_row("BTCUSDT", closed + [forming], now_ms=25 * day + 1000)
        self.assertEqual(row["price"], 130)
        self.assertEqual(row["entry_level"], 110 + 24)  # la vela en formación no mueve el nivel
        self.assertEqual(row["exit_level"], 90 + 15)
        self.assertAlmostEqual(row["gap_to_entry"], 134 / 130 - 1)
        self.assertTrue(row["in_strategy"])
        self.assertFalse(radar_row("ONDOUSDT", closed, now_ms=25 * day + 1000)["in_strategy"])

    def test_radar_needs_twenty_days(self):
        from ai_trading_lab.candles import Candle
        with self.assertRaises(MarketError):
            radar_row("BTCUSDT", [Candle(0, 86_399_999, 1, 1, 1, 1, 1)], now_ms=86_400_000)


class LiquidityTest(unittest.TestCase):
    def test_growth_lags_one_day(self):
        day = 86_400_000
        series = {k * day: 100.0 + k for k in range(40)}
        payload = liquidity_payload(series, days=40)
        self.assertEqual(len(payload["supply"]), 40)
        last = payload["growth_30d"][-1]
        self.assertEqual(last["time"], 39 * day // 1000)
        self.assertAlmostEqual(last["value"], (100.0 + 38) / (100.0 + 8) - 1)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0, state_provider=lambda: {"ok": True},
                                 candles_provider=lambda s, i: {"symbol": s, "interval": i, "candles": []},
                                 liquidity_provider=lambda: {"supply": [], "growth_30d": []},
                                 radar_provider=lambda: {"rows": []})
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, host=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if host:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=5) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_second_server_on_same_port_fails(self):
        # En Windows, SO_REUSEADDR deja que dos procesos compartan el puerto y el viejo sigue contestando.
        with self.assertRaises(OSError):
            make_server(self.port, state_provider=dict, candles_provider=lambda s, i: {})

    def test_binds_only_to_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_state_endpoint(self):
        status, headers, body = self.get("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_rejects_foreign_host_header(self):
        # Protección contra DNS rebinding: una web ajena no puede leer el panel a través del navegador.
        status, _, _ = self.get("/api/state", host="evil.example.com")
        self.assertEqual(status, 403)

    def test_security_headers_on_page(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn(b"<html", body)

    def test_static_files_are_whitelisted(self):
        for path in ["/static/../../.env", "/static/..%2F..%2F.env", "/.env", "/static/nope.js"]:
            status, _, _ = self.get(path)
            self.assertEqual(status, 404, path)

    def test_tv_page_and_assets(self):
        for path, marker in [("/tv", b"/static/tv.js"), ("/static/tv.js", b"wakeLock"), ("/static/tv.css", b".veto")]:
            status, headers, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn(marker, body, path)
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_radar_endpoint(self):
        status, _, body = self.get("/api/radar")
        self.assertEqual((status, json.loads(body)), (200, {"rows": []}))

    def test_liquidity_endpoint(self):
        status, _, body = self.get("/api/liquidity")
        self.assertEqual((status, json.loads(body)), (200, {"supply": [], "growth_30d": []}))

    def test_candles_validation(self):
        self.assertEqual(self.get("/api/candles?symbol=BTCUSDT&interval=1d")[0], 200)
        self.assertEqual(self.get("/api/candles?symbol=DOGEUSDT&interval=1d")[0], 400)

    def test_write_methods_are_refused(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/state", data=b"x", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 405)


if __name__ == "__main__":
    unittest.main()
