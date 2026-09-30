import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.obsidian_sync import END, START, build_notes, ensure_color_groups, merge, safe_name, write_notes

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
STATE = {
    "standing_authorization": {"active": True, "veto_minutes": 1, "max_loss_usdt": 1.2, "min_reward_risk": 1.2, "weekly_loss_limit_usdt": 2.5},
    "portfolio": {"balances": [{"asset": "USDT", "free": "20", "locked": "0"}]},
    "open_positions": [], "agents": [{"agent_id": "claude", "state": "ok", "reason": None, "last_activity": "2026-09-30T11:06:00+00:00"},
                                     {"agent_id": "chatgpt", "state": "ok", "reason": None, "last_activity": "2026-09-30T11:15:00+00:00"}],
    "last_analyses": {}, "strategies": [{"strategy_id": "S-CHANNEL-1D", "status": "LIVE_ELIGIBLE", "name": "Canal", "status_reason": "pasó", "last_verdict": "PASS"},
                                        {"strategy_id": "S-X", "status": "REJECTED", "status_reason": "no pasó"}],
    "forecast": {"latest": [], "skill": []}, "sentiment": {"latest": [], "tone_24h": []}, "ai_thesis": {}, "team": [],
    "timeline": [{"at": "2026-09-30T10:06:00+00:00", "kind": "analysis", "agent": "claude", "title": "DO_NOTHING", "detail": "BTC lateral"}],
}
RADAR = {"rows": [{"symbol": "BTCUSDT", "price": 83000, "gap_to_entry": 0.05, "entry_level": 87150, "exit_level": 80000, "in_strategy": True}]}
WORKSPACE = {"projects": [{"name": "AI Trading Lab", "role": "trading", "commits_7d": 3, "authors_7d": {"Ana": 2}, "recent": [],
                           "repo": {"uncommitted": 1, "ahead": 0, "behind": 0, "unmerged_branches": []}}],
             "pending": [{"level": 2, "who": "Ana", "project": "AI Trading Lab", "text": "rama x sin fusionar"}], "money": {}, "zyneath": None}


class NotesTest(unittest.TestCase):
    def setUp(self):
        self.notes = build_notes(STATE, RADAR, WORKSPACE, [{"id": 34, "created_at": NOW, "message": "silencio = aprobación"}], [], NOW)

    def test_hub_links_the_ecosystem(self):
        tag, body = self.notes["AI Trading Lab.md"]
        self.assertEqual(tag, "centro")
        for name in ("[[Claude]]", "[[Codex]]", "[[Binance Spot]]", "[[S-CHANNEL-1D]]", "[[Decisión 34]]", "[[Equipo]]"):
            self.assertIn(name, body)

    def test_asset_links_its_strategy_and_diary_links_mentions(self):
        self.assertIn("[[S-CHANNEL-1D]]", self.notes["Mercado/BTC.md"][1])
        self.assertIn("[[BTC]]", self.notes["Diario/2026-09-30.md"][1])
        self.assertIn("[[Ana]]", self.notes["Proyectos/AI Trading Lab.md"][1])
        self.assertIn("rama x sin fusionar", self.notes["Equipo.md"][1])
        self.assertIn("Personas/Ana.md", self.notes)


class MindTest(unittest.TestCase):
    def test_memory_is_split_into_linked_memories(self):
        from tools.obsidian_sync import autolinks, mind_notes, split_memory
        text = "---\nname: x\n---\n\nRepo local del laboratorio.\n- 2026-09-24: Binance permisos de Codex revisados.\n  detalle\n- TimesFM necesita memoria.\n"
        chunks = split_memory(text)
        self.assertEqual(len(chunks), 3)
        self.assertIn("detalle", chunks[1][1])
        self.assertEqual(autolinks(chunks[1][1]), ["Binance Spot", "Codex"])
        with tempfile.TemporaryDirectory() as mem:
            (Path(mem) / "MEMORY.md").write_text("- índice", encoding="utf-8")
            (Path(mem) / "infra.md").write_text(text, encoding="utf-8")
            notes = mind_notes(mem, "# AGENTS\n## Roles\nClaude y Codex.\n## Sentimiento\nFear & Greed\n", ["2026-09-30"], ["2026-09-30"])
        self.assertEqual(sum(k.startswith("Claude/Memoria/") for k in notes), 3, "MEMORY.md (el índice) no se copia")
        self.assertIn("[[Sentimiento]]", notes["Protocolo/Sentimiento.md"][1])
        self.assertIn("[[Roles]]", notes["Protocolo/Protocolo de los agentes.md"][1])
        self.assertIn("[[2026-09-30]]", notes["Codex/Mente de Codex.md"][1])


class WriteTest(unittest.TestCase):
    def test_user_text_outside_the_block_survives(self):
        first = merge(None, "agente", "v1")
        edited = first.replace(START, "Mi nota propia\n" + START) + "\nAl final también\n"
        second = merge(edited, "agente", "v2")
        self.assertIn("Mi nota propia", second)
        self.assertIn("Al final también", second)
        self.assertIn("v2", second)
        self.assertNotIn("v1", second)
        self.assertEqual(second.count(END), 1)

    def test_never_writes_outside_its_folder(self):
        with tempfile.TemporaryDirectory() as vault:
            n = write_notes(vault, {"../fuera.md": ("x", "no"), "ok.md": ("x", "sí")})
            self.assertEqual(n, 1)
            self.assertFalse((Path(vault) / "fuera.md").exists())
            self.assertTrue((Path(vault) / "AI Trading Lab" / "ok.md").exists())

    def test_names_are_safe(self):
        self.assertEqual(safe_name('a/b:c*?"d'), "a-b-c---d")

    def test_color_groups_only_when_empty(self):
        with tempfile.TemporaryDirectory() as vault:
            cfg = Path(vault) / ".obsidian" / "graph.json"
            cfg.parent.mkdir()
            cfg.write_text(json.dumps({"colorGroups": [], "scale": 1}), encoding="utf-8")
            self.assertTrue(ensure_color_groups(vault))
            data = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(data["scale"], 1)
            self.assertIn("tag:#agente", [g["query"] for g in data["colorGroups"]])
            self.assertFalse(ensure_color_groups(vault), "no pisa grupos que ya existen")


if __name__ == "__main__":
    unittest.main()
