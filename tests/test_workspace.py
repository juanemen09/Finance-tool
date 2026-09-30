import json
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dashboard.workspace import SEP, WorkspaceCache, git_activity, money_status

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def fake_git(stdout="", returncode=0, stderr=""):
    return lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout=stdout, stderr=stderr)


class GitTest(unittest.TestCase):
    def test_counts_week_and_authors(self):
        lines = "\n".join(SEP.join(x) for x in [
            ("a1", "Juan Emilio", "2026-09-29T10:00:00+00:00", "feat: algo"),
            ("b2", "Claude", "2026-09-28T10:00:00+00:00", "fix: otra"),
            ("c3", "Claude", "2026-09-20T10:00:00+00:00", "docs: vieja")])
        out = git_activity("repo", now=NOW, run=fake_git(lines))
        self.assertEqual(out["commits_7d"], 2)
        self.assertEqual(out["commits_14d"], 3)
        self.assertEqual(out["authors_7d"], {"Juan Emilio": 1, "Claude": 1})
        self.assertEqual(out["recent"][0]["subject"], "feat: algo")

    def test_empty_repository(self):
        out = git_activity("repo", now=NOW, run=fake_git(returncode=128, stderr="does not have any commits yet"))
        self.assertEqual(out, {"error": "sin commits"})


class MoneyTest(unittest.TestCase):
    def test_reads_posts_config_and_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            db = sqlite3.connect(root / "state" / "engine.db")
            db.execute("create table posts (id integer primary key, kind text, topic text, title text, platforms text,"
                       " status text, detail text, video_path text, created_at text)")
            db.execute("insert into posts (kind, topic, title, platforms, status, created_at) values"
                       " ('short', 't', 'Gadget', 'youtube', 'failed', '2026-09-30T01:22:53')")
            db.commit()
            db.close()
            (root / "engine.toml").write_text('[channel]\nshorts_per_day = 1\nplatforms = ["youtube"]\n'
                                              '[moneyprinterturbo]\napi = "http://127.0.0.1:8080/api/v1"\n', encoding="utf-8")
            (root / "state" / "PAUSED").write_text("2026-09-30 prueba", encoding="utf-8")
            out = money_status(root, probe=lambda api: False)
        self.assertEqual(out["counts"], {"failed": 1})
        self.assertTrue(out["paused"])
        self.assertEqual(out["per_day"], 1)
        self.assertFalse(out["video_engine_up"])
        self.assertEqual(out["recent"][0]["title"], "Gadget")

    def test_missing_config_file_is_reported(self):
        self.assertEqual(WorkspaceCache(Path("no-existe.json")).get(), {"configured": False})

    def test_example_config_is_valid_json(self):
        example = Path(__file__).resolve().parent.parent / "config" / "workspace.example.json"
        self.assertIn("projects", json.loads(example.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
