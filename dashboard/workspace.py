"""El resto del ecosistema para el modo TV: money-engine, Zyneath y el avance de cada proyecto. Solo lectura.

Las rutas y metas salen de config/workspace.local.json, fuera de git porque son proyectos privados y el repo es
público. Sin ese archivo, la sección aparece vacía con el aviso de cómo crearlo (ver config/workspace.example.json).
"""
import json
import sqlite3
from contextlib import closing
import subprocess
import threading
import time
import tomllib
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "workspace.local.json"
CACHE_SECONDS = 120
SEP = "\x1f"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # el panel corre con pythonw: sin consolas que parpadeen


def git_activity(path, days=14, now=None, run=subprocess.run):
    """Commits recientes del repositorio: los últimos, cuántos en 7 días y de quién."""
    now = now or datetime.now().astimezone()
    try:
        out = run(["git", "-C", str(path), "log", f"--since={days}.days", "-n", "60", f"--format=%h{SEP}%an{SEP}%cI{SEP}%s"],
                  capture_output=True, text=True, encoding="utf-8", timeout=10, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        return {"error": type(error).__name__}
    if out.returncode != 0:
        return {"error": "sin commits" if "does not have any commits" in out.stderr else "no es un repositorio"}
    commits = []
    for line in out.stdout.splitlines():
        parts = line.split(SEP)
        if len(parts) == 4:
            commits.append({"hash": parts[0], "author": parts[1], "at": parts[2], "subject": parts[3][:140]})
    week = [c for c in commits if datetime.fromisoformat(c["at"]) > now - timedelta(days=7)]
    authors = {}
    for c in week:
        authors[c["author"]] = authors.get(c["author"], 0) + 1
    return {"recent": commits[:6], "commits_7d": len(week), "commits_14d": len(commits), "authors_7d": authors}


def money_status(root, probe=None):
    """Estado de money-engine desde su base SQLite (abierta en solo lectura) y su engine.toml."""
    root = Path(root)
    db = root / "state" / "engine.db"
    if not db.exists():
        return {"error": "sin base de datos"}
    # closing(): el "with" de sqlite3 solo cierra la transacción, no la conexión; money-engine necesita su archivo.
    with closing(sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        counts = {r["status"]: r["n"] for r in conn.execute("select status, count(*) as n from posts group by status")}
        today = conn.execute("select count(*) from posts where status in ('published', 'publishing') "
                             "and created_at >= ?", (datetime.now().strftime("%Y-%m-%d"),)).fetchone()[0]
        recent = [dict(r) for r in conn.execute(
            "select id, kind, title, platforms, status, created_at from posts order by id desc limit 6")]
    try:
        cfg = tomllib.loads((root / "engine.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        cfg = {}
    pause = root / "state" / "PAUSED"
    api = cfg.get("moneyprinterturbo", {}).get("api", "")
    return {"paused": pause.exists(), "pause_note": pause.read_text(encoding="utf-8")[:160] if pause.exists() else None,
            "counts": counts, "published_today": today,
            "per_day": cfg.get("channel", {}).get("shorts_per_day"),
            "platforms": cfg.get("channel", {}).get("platforms", []),
            "niche": cfg.get("channel", {}).get("niche", ""),
            "video_engine_up": (probe or _probe)(api) if api.startswith("http://127.0.0.1") else None,
            "recent": recent}


def _probe(api):
    try:
        with urllib.request.urlopen(api.rstrip("/") + "/ping", timeout=1.5) as r:
            return r.status < 500
    except OSError:
        return False


def build_workspace(config):
    out = {"configured": True, "projects": [], "zyneath": config.get("zyneath"), "money": None}
    for p in config.get("projects", []):
        out["projects"].append({"name": p["name"], "role": p.get("role", ""), **git_activity(p["path"])})
    if config.get("money_engine"):
        try:
            out["money"] = money_status(config["money_engine"])
        except sqlite3.Error as error:
            out["money"] = {"error": type(error).__name__}
    return out


class WorkspaceCache:
    def __init__(self, path=CONFIG):
        self._path, self._lock, self._at, self._value = Path(path), threading.Lock(), 0.0, None

    def get(self):
        with self._lock:
            if self._value is None or time.monotonic() - self._at > CACHE_SECONDS:
                try:
                    config = json.loads(self._path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    self._value = {"configured": False}
                else:
                    self._value = build_workspace(config)
                self._at = time.monotonic()
            return self._value
