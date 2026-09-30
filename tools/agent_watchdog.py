"""Vigilante de agentes: avisa si Claude o Codex dejan de escribir en el diario a su ritmo.

  C:\\Python314\\pythonw.exe tools\\agent_watchdog.py   (tarea «AI Trading Lab\\Vigilante de agentes», cada 15 min)
  python -m tools.agent_watchdog --dry-run            (muestra el diagnóstico sin avisar ni guardar estado)

Lee con el rol dashboard_reader y aplica las reglas de dashboard.health, las mismas que pintan el panel y la TV.
Corre fuera de los agentes a propósito: el 2026-09-26 el ciclo de Claude se quedó 7 horas esperando un permiso y
nadie se enteró, porque el que debía avisar era el agente congelado.

Avisa una vez por incidente (y de nuevo si sigue 12 h después) y cuando el agente se recupera: con una notificación
de Windows y, si .env tiene WATCHDOG_SMTP_USER y WATCHDOG_SMTP_APP_PASSWORD (una contraseña de aplicación de Gmail
que el usuario crea y pega él mismo), también por correo a WATCHDOG_EMAIL_TO o, si falta, a WATCHDOG_SMTP_USER.
"""
import argparse
import json
import os
import smtplib
import ssl
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pythonw lo lanza como script, sin -m
    sys.path.insert(0, str(ROOT))

from dashboard.config import load_env  # noqa: E402
from dashboard.health import agent_health  # noqa: E402
from dashboard.queries import SQL  # noqa: E402

OUT = ROOT / "data" / "raw" / "watchdog"
REMIND_AFTER = timedelta(hours=12)
AGENT_NAMES = {"claude": "Claude", "chatgpt": "Codex"}
# Texto del aviso por variables de entorno, nunca pegado dentro del script de PowerShell.
TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName('text')
$texts.Item(0).AppendChild($template.CreateTextNode($env:WATCHDOG_TITLE)) | Out-Null
$texts.Item(1).AppendChild($template.CreateTextNode($env:WATCHDOG_BODY)) | Out-Null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($template))
"""


def transitions(health, previous, now):
    """Qué avisar comparando con la corrida anterior. Devuelve (avisos, estado nuevo)."""
    alerts, state = [], {}
    for h in health:
        agent, stale = h["agent_id"], h["state"] != "ok"
        prev = previous.get(agent, {})
        alerted_at = prev.get("alerted_at")
        if stale and (not prev.get("stale") or not alerted_at
                      or now - datetime.fromisoformat(alerted_at) >= REMIND_AFTER):
            alerts.append({"agent_id": agent, "kind": "stale", "reason": h.get("reason") or h["state"]})
            alerted_at = now.isoformat()
        elif not stale and prev.get("stale"):
            alerts.append({"agent_id": agent, "kind": "recovered", "reason": None})
            alerted_at = None
        state[agent] = {"stale": stale, "alerted_at": alerted_at if stale else None}
    return alerts, state


def message(alert):
    name = AGENT_NAMES.get(alert["agent_id"], alert["agent_id"])
    if alert["kind"] == "recovered":
        return f"{name} volvió a escribir en el diario", "El vigilante lo ve al día otra vez."
    return (f"{name} está atrasado",
            f"{alert['reason']}. Revisa si su tarea programada espera un permiso o se detuvo.")


def notify_windows(title, body):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # sin consola que tape el modo TV
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", TOAST_PS], timeout=30, check=False,
                   creationflags=flags, env={**os.environ, "WATCHDOG_TITLE": title, "WATCHDOG_BODY": body})


def send_email(env, subject, body):
    user, password = env.get("WATCHDOG_SMTP_USER"), env.get("WATCHDOG_SMTP_APP_PASSWORD")
    if not user or not password:
        return False
    mail = EmailMessage()
    mail["From"], mail["To"], mail["Subject"] = user, env.get("WATCHDOG_EMAIL_TO") or user, subject
    mail.set_content(body + "\n\nAviso automático del vigilante de agentes de AI Trading Lab (tools/agent_watchdog.py).")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as smtp:
        smtp.login(user, password)
        smtp.send_message(mail)
    return True


def read_health(url, now):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=15,
                         application_name="ai-trading-lab-watchdog") as conn:
        activity = conn.execute(SQL["activity"]).fetchall()
        pending = conn.execute(SQL["pending"]).fetchall()
    return agent_health(activity, pending, now)


def log(line):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "log.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ} {line}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    env = load_env()
    url = env.get("DASHBOARD_DATABASE_URL", "")
    user = urlsplit(url).username or ""
    if user != "dashboard_reader" and not user.startswith("dashboard_reader."):  # en Supabase: dashboard_reader.<ref>
        log("error: falta DASHBOARD_DATABASE_URL con el rol dashboard_reader en .env")
        return 1
    now = datetime.now(timezone.utc)
    try:
        health = read_health(url, now)
    except Exception as error:  # sin internet o base caída: queda en el registro, no revienta la tarea
        log(f"error: no se pudo leer el diario ({type(error).__name__})")
        return 1
    if args.dry_run:
        print(json.dumps(health, default=str, ensure_ascii=False, indent=1))
        return 0

    state_path = OUT / "state.json"
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        previous = {}
    alerts, state = transitions(health, previous.get("agents", {}), now)
    for alert in alerts:
        title, body = message(alert)
        channels = []
        try:
            notify_windows(title, body)
            channels.append("windows")
        except Exception as error:
            log(f"error: notificación de Windows ({type(error).__name__})")
        try:
            if send_email(env, title, body):
                channels.append("correo")
        except Exception as error:  # nunca se registra el mensaje de error: podría repetir la credencial
            log(f"error: correo ({type(error).__name__})")
        log(f"{alert['kind']} {alert['agent_id']}: {alert['reason'] or 'al día'} -> {', '.join(channels) or 'sin canal'}")
    OUT.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"last_run": now.isoformat(), "agents": state}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
