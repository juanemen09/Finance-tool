import unittest
from datetime import datetime, timedelta, timezone

from tools.agent_watchdog import message, send_email, transitions

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def health(claude="ok", chatgpt="ok"):
    return [{"agent_id": "claude", "state": claude, "reason": "sin escribir hace 90 min" if claude != "ok" else None},
            {"agent_id": "chatgpt", "state": chatgpt, "reason": None}]


class TransitionsTest(unittest.TestCase):
    def test_first_stale_run_alerts_once(self):
        alerts, state = transitions(health(claude="atrasado"), {}, NOW)
        self.assertEqual([(a["agent_id"], a["kind"]) for a in alerts], [("claude", "stale")])
        again, _ = transitions(health(claude="atrasado"), state, NOW + timedelta(minutes=15))
        self.assertEqual(again, [], "el mismo incidente no se repite cada 15 minutos")

    def test_reminds_after_twelve_hours(self):
        _, state = transitions(health(claude="atrasado"), {}, NOW)
        alerts, _ = transitions(health(claude="atrasado"), state, NOW + timedelta(hours=12))
        self.assertEqual([a["kind"] for a in alerts], ["stale"])

    def test_recovery_is_announced(self):
        _, state = transitions(health(claude="atrasado"), {}, NOW)
        alerts, state = transitions(health(), state, NOW + timedelta(minutes=30))
        self.assertEqual([(a["agent_id"], a["kind"]) for a in alerts], [("claude", "recovered")])
        self.assertEqual(state["claude"], {"stale": False, "alerted_at": None})

    def test_healthy_agents_stay_quiet(self):
        alerts, state = transitions(health(), {}, NOW)
        self.assertEqual(alerts, [])
        self.assertFalse(state["chatgpt"]["stale"])

    def test_never_active_agent_counts_as_stale(self):
        alerts, _ = transitions(health(chatgpt="sin actividad"), {}, NOW)
        self.assertEqual([(a["agent_id"], a["reason"]) for a in alerts], [("chatgpt", "sin actividad")])


class MessageTest(unittest.TestCase):
    def test_texts(self):
        title, body = message({"agent_id": "chatgpt", "kind": "stale", "reason": "no escribió su análisis diario"})
        self.assertEqual(title, "Codex está atrasado")
        self.assertIn("no escribió su análisis diario", body)
        self.assertIn("volvió", message({"agent_id": "claude", "kind": "recovered", "reason": None})[0])

    def test_email_is_optional(self):
        self.assertFalse(send_email({}, "t", "b"))
        self.assertFalse(send_email({"WATCHDOG_SMTP_USER": "a@b.c"}, "t", "b"))


if __name__ == "__main__":
    unittest.main()
