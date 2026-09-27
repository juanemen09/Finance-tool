"""Doctor del entorno local de un miembro del equipo. Solo mira tu PC: no se conecta a nada y nunca imprime el valor
de una variable del .env, solo si está o no."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dashboard.config import load_env

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {"numpy": "numpy", "vaderSentiment": "vaderSentiment", "psycopg": "psycopg"}
OK, WARN, FAIL = "OK", "AVISO", "FALLA"


def run_checks(root=ROOT, env=None, python=sys.version_info, which=shutil.which, git_config=None):
    env = load_env(Path(root) / ".env") if env is None else env
    git_config = _git_config if git_config is None else git_config
    checks = []

    checks.append((OK, "Python", "{}.{}".format(*python[:2])) if python[:2] >= (3, 11)
                  else (FAIL, "Python", "Hace falta 3.11 o más nuevo; tienes {}.{}".format(*python[:2])))

    missing = [name for name, module in PACKAGES.items() if importlib.util.find_spec(module) is None]
    checks.append((FAIL, "Dependencias", f"Faltan {', '.join(missing)}: pip install -r requirements.txt")
                  if missing else (OK, "Dependencias", "requirements.txt instalado"))

    if which("git") is None:
        checks.append((FAIL, "git", "No está instalado"))
    else:
        name, email = git_config("user.name"), git_config("user.email")
        checks.append((OK, "git", f"Firmas como {name}") if name and email
                      else (WARN, "git", "Configura git config --global user.name y user.email"))

    checks += _env_checks(env)

    for tool, why in (("node", "PraxiGuard (Node.js 24)"), ("docker", "pruebas de esquema y Supabase local")):
        checks.append((OK, tool, "instalado") if which(tool) else (WARN, tool, f"No instalado; solo si trabajas en {why}"))
    return checks


def _env_checks(env):
    checks = []
    url = env.get("DASHBOARD_DATABASE_URL")
    if not url:
        checks.append((WARN, "Centro de mando", "Sin DASHBOARD_DATABASE_URL en .env (paso 'panel' del onboarding)"))
    else:
        user = (urlsplit(url).username or "").split(".")[0]
        if user.startswith("team_"):
            checks.append((OK, "Centro de mando", f"Rol personal {user}"))
        elif user == "dashboard_reader":
            checks.append((WARN, "Centro de mando", "Usas el rol compartido del fundador; pídele tu rol team_<handle>"))
        else:
            checks.append((FAIL, "Centro de mando", f"El rol {user or '(vacío)'} no es de solo lectura del equipo"))
    # Credenciales que un miembro del equipo no debe tener: son de los agentes o del fundador.
    for key in ("INGEST_DATABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "BINANCE_API_KEY", "BINANCE_SECRET_KEY"):
        if env.get(key):
            checks.append((FAIL, key, "No la necesitas: bórrala de tu .env y avisa al fundador para rotarla"))
    return checks


def _git_config(key):
    try:
        out = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def render(checks):
    width = max(len(name) for _, name, _ in checks)
    return "\n".join(f"[{status:5}] {name:{width}}  {message}" for status, name, message in checks)
