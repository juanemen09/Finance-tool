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


class TeamTest(unittest.TestCase):
    def test_github_slug(self):
        from dashboard.workspace import github_slug
        self.assertEqual(github_slug("https://github.com/juanemen09/Finance-tool.git"), "juanemen09/Finance-tool")
        self.assertEqual(github_slug("git@github.com:ana/repo.git"), "ana/repo")
        self.assertIsNone(github_slug("https://gitlab.com/x/y.git"))

    def test_pending_orders_by_urgency_and_names_who(self):
        from dashboard.workspace import team_pending
        projects = [{"name": "Lab", "repo": {"github": "a/b", "uncommitted": 2, "ahead": 1, "behind": 0,
                                             "unmerged_branches": [{"branch": "feat-x", "author": "Ana", "at": "2026-09-29T00:00:00Z"}]},
                     "github_items": {"pulls": [{"number": 7, "title": "Nueva vista", "author": "ana", "draft": False, "reviewers": [], "created_at": "2026-09-28T00:00:00Z"}],
                                      "issues": [{"number": 3, "title": "Bug", "author": "x", "assignees": [], "created_at": "2026-09-27T00:00:00Z"}]}},
                    {"name": "Sin remoto", "repo": {"github": None, "uncommitted": 0}}]
        items = team_pending(projects)
        texts = [i["text"] for i in items]
        self.assertEqual(items[0]["level"], 3)
        self.assertIn("1 commit(s) sin push en None", texts)
        self.assertIn("rama feat-x sin fusionar", texts)
        self.assertTrue(any("PR #7" in t for t in texts))
        self.assertTrue(any(i["who"] == "sin asignar" for i in items))
        self.assertTrue(any("sin remoto" in t for t in texts))

    def test_repo_status_reads_git(self):
        from dashboard.workspace import repo_status
        answers = {"remote": "https://github.com/a/b.git", "rev-parse": "main", "status": " M x.py\n?? y.py\n",
                   "rev-list": "2\t1", "symbolic-ref": "origin/main", "for-each-ref": "origin/main\tA\t2026\norigin/feat\tAna\t2026-09-29T00:00:00Z\n"}

        def run(cmd, **kwargs):
            sub = cmd[3]
            if sub == "merge-base":
                return subprocess.CompletedProcess(cmd, 1, "", "")  # la rama no está fusionada
            return subprocess.CompletedProcess(cmd, 0, answers.get(sub, ""), "")
        out = repo_status("repo", fetch=False, run=run)
        self.assertEqual((out["uncommitted"], out["behind"], out["ahead"]), (2, 2, 1))
        self.assertEqual(out["github"], "a/b")
        self.assertEqual(out["unmerged_branches"], [{"branch": "feat", "author": "Ana", "at": "2026-09-29T00:00:00Z"}])


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
