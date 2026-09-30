"""El resto del ecosistema para el modo TV: money-engine, Zyneath y el avance de cada proyecto. Solo lectura.

Las rutas y metas salen de config/workspace.local.json, fuera de git porque son proyectos privados y el repo es
público. Sin ese archivo, la sección aparece vacía con el aviso de cómo crearlo (ver config/workspace.example.json).
"""
import json
import os
import re
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


FETCH_SECONDS = 600
GITHUB_SECONDS = 600
_last_fetch = {}
_github_cache = {}


def _git(path, *args, timeout=15, run=subprocess.run):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # un repositorio que pida credenciales falla en vez de colgarse
    return run(["git", "-C", str(path), *args], capture_output=True, text=True, encoding="utf-8", timeout=timeout,
               creationflags=NO_WINDOW, env=env)


def github_slug(url):
    """owner/repo de una URL de GitHub (https o ssh); None si no es GitHub."""
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def repo_status(path, fetch=True, run=subprocess.run, now=None):
    """Lo que falta hacer en el repositorio: cambios sin commit, commits sin push, commits por traer y ramas remotas
    sin fusionar (con su autor). Lo local solo ve esta computadora; lo remoto, lo que cada persona ya subió."""
    now = now or time.time()
    out = {}
    try:
        url = _git(path, "remote", "get-url", "origin", run=run).stdout.strip()
        out["github"] = github_slug(url)
        if fetch and url and now - _last_fetch.get(str(path), 0) > FETCH_SECONDS:
            _last_fetch[str(path)] = now
            _git(path, "fetch", "--quiet", "--prune", timeout=25, run=run)
        out["branch"] = _git(path, "rev-parse", "--abbrev-ref", "HEAD", run=run).stdout.strip()
        dirty = [line[3:] for line in _git(path, "status", "--porcelain", run=run).stdout.splitlines() if line.strip()]
        out["uncommitted"], out["uncommitted_files"] = len(dirty), dirty[:6]
        counts = _git(path, "rev-list", "--left-right", "--count", "@{u}...HEAD", run=run)
        if counts.returncode == 0 and counts.stdout.split():
            behind, ahead = (int(x) for x in counts.stdout.split()[:2])
            out["behind"], out["ahead"] = behind, ahead
        else:
            out["behind"], out["ahead"] = None, None  # la rama no sigue a ninguna remota
        default = _git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", run=run).stdout.strip() or "origin/main"
        refs = _git(path, "for-each-ref", "refs/remotes/origin", "--format=%(refname:short)%09%(authorname)%09%(committerdate:iso-strict)", run=run)
        unmerged = []
        for line in refs.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3 or parts[0] in (default, "origin/HEAD", "origin"):
                continue
            if _git(path, "merge-base", "--is-ancestor", parts[0], default, run=run).returncode != 0:
                unmerged.append({"branch": parts[0].removeprefix("origin/"), "author": parts[1], "at": parts[2]})
        out["unmerged_branches"] = unmerged
    except (OSError, subprocess.SubprocessError) as error:
        out["error"] = type(error).__name__
    return out


def _gh_ready(run=subprocess.run):
    try:
        return run(["gh", "auth", "status"], capture_output=True, timeout=10, creationflags=NO_WINDOW).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _github_get(path, use_gh, run=subprocess.run):
    if use_gh:
        r = run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8", timeout=20, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise OSError("gh api falló")
        return json.loads(r.stdout)
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={"Accept": "application/vnd.github+json",
                                                                          "User-Agent": "ai-trading-lab-dashboard"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def github_items(slug, run=subprocess.run, get=None):
    """PR abiertos (esperan fusión) e issues abiertos con su responsable. Con `gh auth login` ve también los repos
    privados; sin sesión, solo los públicos."""
    hit = _github_cache.get(slug)
    if hit and time.monotonic() - hit[0] < GITHUB_SECONDS:
        return hit[1]
    use_gh = _gh_ready(run)
    get = get or (lambda p: _github_get(p, use_gh, run))
    try:
        pulls = get(f"repos/{slug}/pulls?state=open&per_page=30")
        issues = [i for i in get(f"repos/{slug}/issues?state=open&per_page=30") if "pull_request" not in i]
        value = {
            "pulls": [{"number": p["number"], "title": p["title"][:120], "author": p["user"]["login"], "draft": p.get("draft", False),
                       "created_at": p["created_at"], "reviewers": [r["login"] for r in p.get("requested_reviewers", [])]} for p in pulls],
            "issues": [{"number": i["number"], "title": i["title"][:120], "author": i["user"]["login"],
                        "assignees": [a["login"] for a in i.get("assignees", [])], "created_at": i["created_at"]} for i in issues],
            "auth": "gh" if use_gh else "público"}
    except (OSError, ValueError, KeyError) as error:
        value = {"error": "sin acceso (repo privado: inicia sesión con gh auth login)" if not use_gh else type(error).__name__}
    _github_cache[slug] = (time.monotonic(), value)
    return value


def team_pending(projects, members=()):
    """Lista única de pendientes, de lo más urgente a lo menos, con quién debe actuar."""
    items = []
    for p in projects:
        repo = p.get("repo") or {}
        who = "Juan Emilio (esta PC)"
        if p.get("repo") is not None and not repo.get("github") and not repo.get("error"):
            items.append({"level": 3, "who": who, "project": p["name"], "text": "sin remoto en GitHub: el trabajo no está respaldado"})
        if (p.get("github_items") or {}).get("error"):
            items.append({"level": 1, "who": who, "project": p["name"], "text": p["github_items"]["error"]})
        if repo.get("uncommitted"):
            items.append({"level": 2, "who": who, "project": p["name"], "text": f"{repo['uncommitted']} archivo(s) sin commit"})
        if repo.get("ahead"):
            items.append({"level": 3, "who": who, "project": p["name"], "text": f"{repo['ahead']} commit(s) sin push en {repo.get('branch')}"})
        if repo.get("behind"):
            items.append({"level": 1, "who": who, "project": p["name"], "text": f"{repo['behind']} commit(s) del remoto por traer (pull)"})
        for b in repo.get("unmerged_branches", []):
            items.append({"level": 2, "who": b["author"], "project": p["name"], "text": f"rama {b['branch']} sin fusionar"})
        gh = p.get("github_items") or {}
        for pr in gh.get("pulls", []):
            items.append({"level": 3, "who": pr["author"], "project": p["name"],
                          "text": f"PR #{pr['number']} {'(borrador) ' if pr['draft'] else ''}espera fusión: {pr['title']}",
                          "reviewers": pr["reviewers"], "at": pr["created_at"]})
        for i in gh.get("issues", []):
            items.append({"level": 1, "who": ", ".join(i["assignees"]) or "sin asignar", "project": p["name"],
                          "text": f"issue #{i['number']} abierto: {i['title']}", "at": i["created_at"]})
    return sorted(items, key=lambda x: -x["level"])


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
    owner = config.get("github_owner", "")
    for p in config.get("projects", []):
        project = {"name": p["name"], "role": p.get("role", ""), **git_activity(p["path"])}
        if p.get("track", True):
            project["repo"] = repo_status(p["path"], fetch=bool(owner))
            slug = project["repo"].get("github")
            # solo los repos propios: el clon de un proyecto ajeno (p. ej. TimesFM de Google) no es trabajo del equipo
            if slug and owner and slug.split("/")[0].lower() == owner.lower():
                project["github_items"] = github_items(slug)
        out["projects"].append(project)
    out["pending"] = team_pending(out["projects"])
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
