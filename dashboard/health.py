"""Salud de los agentes según el ritmo de cada uno. La usan el panel, el modo TV y el vigilante.

Desde el 2026-09-30 los dos agentes escriben en el diario al menos una vez por hora (pedido del usuario: interacción
continua, como una terminal). Claude corre en el minuto :06 y Codex en el :15, así que a Codex se le da algo más de
margen antes de marcarlo atrasado.
"""
AGENTS = ("claude", "chatgpt")
STALE_MINUTES = {"claude": 75, "chatgpt": 90}
MAILBOX_MINUTES = {"claude": 75, "chatgpt": 90}


def stale_reason(agent, last_at, pending, now):
    """Por qué el agente está atrasado, o None si va a su ritmo."""
    minutes = int((now - last_at).total_seconds() // 60)
    if minutes > STALE_MINUTES[agent]:
        return f"sin escribir en el diario hace {minutes} min (escribe cada hora)"
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
