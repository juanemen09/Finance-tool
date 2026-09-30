"""Salud de los agentes según el ritmo de cada uno. La usan el panel, el modo TV y el vigilante.

Claude escribe en el diario cada hora (minuto :06). Codex, desde el 2026-09-27, escribe su análisis una vez al día
en la ventana de 00:15 a 01:45 UTC y el resto del día solo atiende el buzón cada 4 horas: medirlo por minutos sin
actividad, como a Claude, lo pondría en rojo casi todo el día y el aviso dejaría de significar algo.
"""
from datetime import timedelta

AGENTS = ("claude", "chatgpt")
CLAUDE_STALE_MINUTES = 75
CODEX_DEADLINE_HOUR_UTC = 2  # la ventana diaria de Codex termina a las 01:45 UTC
MAILBOX_MINUTES = {"claude": 75, "chatgpt": 285}  # Codex revisa el buzón cada 4 h; 45 min de margen


def codex_cycle_start(now):
    """Inicio (00:00 UTC) del último día cuyo análisis de Codex ya debería existir."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day if now >= day + timedelta(hours=CODEX_DEADLINE_HOUR_UTC) else day - timedelta(days=1)


def stale_reason(agent, last_at, pending, now):
    """Por qué el agente está atrasado, o None si va a su ritmo."""
    if agent == "claude" and (now - last_at) > timedelta(minutes=CLAUDE_STALE_MINUTES):
        return f"sin escribir en el diario hace {int((now - last_at).total_seconds() // 60)} min (escribe cada hora)"
    if agent == "chatgpt" and last_at < codex_cycle_start(now):
        return f"no escribió su análisis diario del ciclo {codex_cycle_start(now):%Y-%m-%d}T00Z"
    if pending:
        waiting = int((now - pending["oldest"]).total_seconds() // 60)
        if waiting > MAILBOX_MINUTES[agent]:
            return f"{pending['n']} mensaje(s) sin atender en su buzón desde hace {waiting} min"
    return None


def agent_health(activity_rows, pending_rows, now):
    last = {r["agent_id"]: r["created_at"] for r in activity_rows}
    pending = {r["to_agent_id"]: r for r in pending_rows}
    out = []
    for agent in AGENTS:
        at = last.get(agent)
        if at is None:
            out.append({"agent_id": agent, "last_activity": None, "minutes_since": None, "state": "sin actividad",
                        "reason": "nunca escribió en el diario", "pending_messages": 0})
            continue
        reason = stale_reason(agent, at, pending.get(agent), now)
        out.append({"agent_id": agent, "last_activity": at, "minutes_since": int((now - at).total_seconds() // 60),
                    "state": "atrasado" if reason else "ok", "reason": reason,
                    "pending_messages": pending.get(agent, {}).get("n", 0)})
    return out
