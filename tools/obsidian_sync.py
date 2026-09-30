"""Escribe el laboratorio como notas enlazadas en la bóveda de Obsidian del usuario: su grafo de conocimiento.

  C:\\Python314\\pythonw.exe tools\\obsidian_sync.py   (tarea «AI Trading Lab\\Obsidian», cada hora)
  python -m tools.obsidian_sync --dry-run            (muestra las notas que escribiría, sin tocar la bóveda)

- Solo escribe dentro de <bóveda>/AI Trading Lab/. No toca ni borra ninguna otra nota.
- En cada nota reemplaza solo el bloque entre los marcadores de abajo: lo que el usuario escriba fuera se conserva.
- Lee el diario con el rol dashboard_reader. La ruta de la bóveda va en config/workspace.local.json
  (`obsidian_vault`), fuera de git. Las notas llevan datos del diario, nunca claves ni conexiones.
- Claude y Codex leen estas notas (sobre todo «Contexto de los agentes») para retomar el hilo entre sesiones.
- También escribe la «mente» de los agentes: la memoria de Claude (`claude_memory_dir` en la configuración local),
  partida en recuerdos, y cada sección de AGENTS.md, el protocolo que comparten. Todo se enlaza por conceptos.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pythonw lo lanza como script, sin -m
    sys.path.insert(0, str(ROOT))

from dashboard.config import load_env  # noqa: E402
from dashboard.queries import build_state  # noqa: E402

FOLDER = "AI Trading Lab"
START, END = "<!-- ai-trading-lab:inicio (se regenera cada hora; escribe fuera de este bloque) -->", "<!-- ai-trading-lab:fin -->"
AGENT = {"claude": "Claude", "chatgpt": "Codex"}
# Colores del grafo de Obsidian por etiqueta (0xRRGGBB), los mismos del modo TV.
COLOR_GROUPS = [("agente", 0x45E0B0), ("activo", 0x6FD3FF), ("estrategia", 0xAA8CFF), ("investigacion", 0xFFD66E),
                ("regla", 0xFFB547), ("decision", 0xFF4D6D), ("proyecto", 0x5A96FF), ("persona", 0xEBF0FF),
                ("pendiente", 0xFF9F43), ("diario", 0x8A9BC8), ("centro", 0xFF4D6D),
                ("memoria-claude", 0x7CFFCB), ("protocolo", 0xC9B6FF), ("memoria-codex", 0xFF6B8A),
                ("bitacora-codex", 0xFF8FA3),
                ("tesis-exitosa", 0x2EE59D), ("tesis-fallida", 0xFF3355), ("anomalia", 0xFFC400), ("hora", 0x4F6DB8)]
STATIC = ROOT / "docs" / "obsidian"  # plantilla y tablero: se copian solo si no existen (nunca pisan cambios del usuario)
EXTRA_SQL = {
    "decisions": "select id, created_at, message from events where kind = 'user_decision' order by id",
    "limits": "select id, created_at, active, veto_minutes, max_loss_usdt, min_reward_risk, weekly_loss_limit_usdt, "
              "user_message_quote from standing_authorizations order by id",
    "codex_analyses": "select analysis_id, cycle_id, created_at, market_regime, proposed_action, thesis, risk_factors, "
                      "confidence_context from analyses where agent_id = 'chatgpt' order by created_at desc limit 336",
}


def safe_name(name):
    """Nombre de archivo válido en Windows y que no escape de la carpeta."""
    clean = re.sub(r'[<>:"/\\|?*#^\[\]]', "-", str(name)).strip(" .")
    return clean[:90] or "sin nombre"


def link(name):
    return f"[[{safe_name(name)}]]"


def fmt(v, d=2):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{d}f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def build_notes(state, radar, workspace, decisions, limits, now):
    """{ruta relativa: (etiqueta, cuerpo)} — puro, sin E/S, para poder probarlo."""
    notes = {}

    def note(path, tag, lines):
        notes[path] = (tag, "\n".join(line for line in lines if line is not None))

    sa = state.get("standing_authorization") or {}
    usdt = sum(float(b.get("free", 0)) + float(b.get("locked", 0))
               for b in (state.get("portfolio") or {}).get("balances", []) if b.get("asset") == "USDT")
    projects = (workspace or {}).get("projects", [])
    rows = [r for r in (radar or {}).get("rows", []) if not r.get("error")]
    strategies = state.get("strategies", [])
    alive = [s for s in strategies if s["status"] not in ("REJECTED", "NOT_APPLICABLE")]
    rejected = [s for s in strategies if s["status"] == "REJECTED"]
    f7 = {f["symbol"]: f for f in (state.get("forecast") or {}).get("latest", []) if f["horizon_days"] == 7}
    tone = {t["symbol"]: t for t in (state.get("sentiment") or {}).get("tone_24h", [])}

    dec_links = ", ".join(link(f"Decisión {d['id']}") for d in decisions) or "—"
    agents_line = "; ".join(f"{AGENT.get(a['agent_id'])} {a['state']}" for a in state.get("agents", []))
    note("AI Trading Lab.md", "centro", [
        f"# AI Trading Lab", f"Actualizado {now:%Y-%m-%d %H:%M} UTC.", "",
        f"- Saldo: **{fmt(usdt)} USDT** en {link('Binance Spot')}; {len(state.get('open_positions', []))} posición(es) abierta(s).",
        f"- Piloto automático {'encendido' if sa.get('active') else 'apagado'} · {link('Reglas de riesgo')}.",
        f"- Dirige {link('Juan Emilio')}. Agentes: {link('Claude')} (investiga y revisa) y {link('Codex')} (único ejecutor).",
        f"- Estrategias: {', '.join(link(s['strategy_id']) for s in alive) or '—'} · {link('Estrategias rechazadas')}.",
        f"- Investigación: {link('TimesFM')}, {link('Tesis IA')}, {link('Sentimiento')}.",
        f"- Ecosistema: {', '.join(link(p['name']) for p in projects)}, {link('Money Printer')}, {link('Zyneath')}.",
        f"- {link('Equipo')} · {link(CONTEXT_NOTE)} · decisiones: {dec_links}.",
        f"- Mente de los agentes: {link('Mente de Claude')}, {link('Mente de Codex')}, {link('Protocolo de los agentes')}.",
    ])

    for a in state.get("agents", []):
        name = AGENT.get(a["agent_id"], a["agent_id"])
        la = (state.get("last_analyses") or {}).get(a["agent_id"]) or {}
        other = "Codex" if name == "Claude" else "Claude"
        note(f"Agentes/{name}.md", "agente", [
            f"# {name}", f"Parte de {link('AI Trading Lab')}. Revisión cruzada con {link(other)}.", "",
            f"- Estado: **{a['state']}**" + (f" — {a['reason']}" if a.get("reason") else "") + f" (última actividad {a.get('last_activity') or '—'}).",
            f"- Último análisis: {la.get('proposed_action', '—')} · ciclo {la.get('cycle_id', '—')}.",
            f"- Régimen visto: {la.get('market_regime', '—')}" if la else None,
            f"- Rol: {'único ejecutor en ' + link('Binance Spot') if name == 'Codex' else 'solo lectura en ' + link('Binance Spot') + '; alimenta ' + link('TimesFM') + ', ' + link('Tesis IA') + ' y ' + link('Sentimiento')}.",
        ])

    note("Mercado/Binance Spot.md", "activo", [
        "# Binance Spot", f"Cuenta de {link('AI Trading Lab')}; ejecuta {link('Codex')}, lee {link('Claude')}.", "",
        f"- Saldo: {fmt(usdt)} USDT.", f"- Pares: {', '.join(link(r['symbol'].replace('USDT', '')) for r in rows)}.",
    ])
    channel = [s["strategy_id"] for s in alive if s["strategy_id"].startswith("S-CHANNEL-1D")]
    for r in rows:
        sym = r["symbol"].replace("USDT", "")
        f = f7.get(r["symbol"])
        t = tone.get(r["symbol"])
        note(f"Mercado/{sym}.md", "activo", [
            f"# {sym}", f"Cotiza en {link('Binance Spot')}.", "",
            f"- Precio: {fmt(r['price'], 4)} USDT · a {fmt(r['gap_to_entry'] * 100, 1)} % del máximo de 20 días ({fmt(r['entry_level'], 4)}).",
            f"- Salida del canal si cierra bajo {fmt(r['exit_level'], 4)}.",
            f"- Lo vigilan: {', '.join(link(c) for c in channel)}." if r.get("in_strategy") and channel else "- Fuera de S-CHANNEL-1D.",
            f"- {link('TimesFM')} a 7 días: mediana {fmt(f['median_return'] * 100, 1)} %." if f else None,
            f"- {link('Sentimiento')} 24 h: tono {fmt(t['avg_sentiment'])} en {t['items']} titulares." if t else None,
        ])

    for s in alive:
        note(f"Estrategias/{safe_name(s['strategy_id'])}.md", "estrategia", [
            f"# {s['strategy_id']}", f"Estrategia de {link('AI Trading Lab')} · estado **{s['status']}**.", "",
            f"- {s.get('name') or ''}", f"- Motivo: {s.get('status_reason') or '—'}",
            f"- Último veredicto: {s.get('last_verdict') or '—'}",
            f"- Activos: {', '.join(link(r['symbol'].replace('USDT', '')) for r in rows if r.get('in_strategy'))}." if s["strategy_id"].startswith("S-CHANNEL-1D") else None,
            f"- Límites que la gobiernan: {link('Reglas de riesgo')}." if s["status"] == "LIVE_ELIGIBLE" else None,
        ])
    note("Estrategias/Estrategias rechazadas.md", "estrategia", [
        "# Estrategias rechazadas", f"Descartadas por el hard testing de {link('AI Trading Lab')}.", "",
        *[f"- {s['strategy_id']}: {s.get('status_reason') or '—'}" for s in rejected]])

    fs = (state.get("forecast") or {}).get("skill", [])
    note("Investigación/TimesFM.md", "investigacion", [
        "# TimesFM 3.0", f"Pronóstico en papel que cita {link('Claude')}. Se decide a los 60 cierres (≈ 6 dic).", "",
        *[f"- {link(sym.replace('USDT', ''))}: mediana 7 d {fmt(f['median_return'] * 100, 1)} %" for sym, f in f7.items()],
        *[f"- {x['horizon_days']} d: {x['scored']} puntuados, dirección {fmt((x['direction_hit_rate'] or 0) * 100, 0)} %" for x in fs]])
    thesis = state.get("ai_thesis") or {}
    neck = thesis.get("AI_BOTTLENECK") or {}
    book = ((thesis.get("13F_BOOK") or {}).get("data") or {}).get("book", [])
    note("Investigación/Tesis IA.md", "investigacion", [
        "# Tesis de infraestructura de IA", f"Investigación mensual de {link('Claude')}; no se opera aquí.", "",
        f"## {neck.get('title', 'Cuello de botella')}", neck.get("body", "Pendiente."), "",
        "## 13F de Situational Awareness", *[f"- {b.get('ticker') or b.get('issuer')}: {fmt(b['weight'] * 100, 1)} %" for b in book[:10]]])
    fg = next((x for x in (state.get("sentiment") or {}).get("latest", []) if x["metric"] == "fear_greed"), None)
    note("Investigación/Sentimiento.md", "investigacion", [
        "# Sentimiento", f"Contexto (no señal) que recoge {link('Claude')}.", "",
        f"- Fear & Greed: {fmt(fg['value'], 0)} ({fg.get('label') or ''})." if fg else None,
        *[f"- {link(sym.replace('USDT', ''))}: tono {fmt(t['avg_sentiment'])} ({t['items']})" for sym, t in tone.items() if sym != "MERCADO"]])

    note("Reglas/Reglas de riesgo.md", "regla", [
        "# Reglas de riesgo", f"Las fija {link('Juan Emilio')}; limitan a {link('Codex')} y {link('Claude')}.", "",
        f"- Veto {sa.get('veto_minutes', '—')} min · pérdida máx. {fmt(sa.get('max_loss_usdt'))} USDT · R:R mín. {fmt(sa.get('min_reward_risk'), 1)} · pérdida semanal máx. {fmt(sa.get('weekly_loss_limit_usdt'))} USDT.",
        "- Fijo: solo Spot, 5 pares, 7 USDT por posición, 1 posición, solo estrategias LIVE_ELIGIBLE.", "",
        "## Historia", *[f"- Fila {x['id']} ({str(x['created_at'])[:10]}): veto {x['veto_minutes']} min, pérdida {fmt(x['max_loss_usdt'])}, R:R {fmt(x['min_reward_risk'], 1)}, semanal {fmt(x['weekly_loss_limit_usdt'])}. Cita: {x['user_message_quote'][:300]}" for x in limits]])
    for d in decisions:
        note(f"Decisiones/Decisión {d['id']}.md", "decision", [
            f"# Decisión {d['id']} · {str(d['created_at'])[:10]}", f"Tomada por {link('Juan Emilio')}; afecta a {link('Reglas de riesgo')} y {link('Codex')}.", "",
            d["message"]])

    people = {}
    for p in projects:
        repo = p.get("repo") or {}
        gh = p.get("github_items") or {}
        for author in (p.get("authors_7d") or {}) if p.get("repo") is not None else ():  # un clon ajeno no aporta personas
            people.setdefault(author, set()).add(p["name"])
        note(f"Proyectos/{safe_name(p['name'])}.md", "proyecto", [
            f"# {p['name']}", f"{p.get('role', '')} · lo construye {link('Juan Emilio')}.", "",
            f"- Commits en 7 días: {p.get('commits_7d', '—')} · autores: {', '.join(link(a) for a in (p.get('authors_7d') or {})) or '—'}.",
            f"- Último: {p['recent'][0]['subject']} ({p['recent'][0]['at'][:10]})" if p.get("recent") else None,
            f"- Sin commit: {repo.get('uncommitted', '—')} · sin push: {repo.get('ahead', '—')} · por traer: {repo.get('behind', '—')} · ramas sin fusionar: {len(repo.get('unmerged_branches', []))}." if repo else None,
            f"- PR abiertos: {len(gh.get('pulls', []))} · issues abiertos: {len(gh.get('issues', []))}." if gh and not gh.get("error") else None,
            f"- Producto de {link('Zyneath')}." if re.search("zyneath|medflow", p["name"], re.I) else None,
            f"- Motor de {link('Money Printer')}." if p["name"] == "money-engine" else None,
            f"- Código de {link('AI Trading Lab')}." if p["name"] == "AI Trading Lab" else None,
        ])
    team = state.get("team", [])
    note("Personas/Juan Emilio.md", "persona", [
        "# Juan Emilio", f"Fundador. Dirige {link('AI Trading Lab')}, fija {link('Reglas de riesgo')}, funda {link('Zyneath')} y gana con {link('Money Printer')}.", "",
        f"- Proyectos: {', '.join(link(p['name']) for p in projects)}.",
        "- Su silencio tras la ventana de veto es aprobación (Decisión 34)."])
    for author, projs in people.items():
        if re.search("juan|juanemen", author, re.I) or author == "Claude":
            continue
        note(f"Personas/{safe_name(author)}.md", "persona", [f"# {author}", f"Trabaja en {', '.join(link(x) for x in sorted(projs))}.", f"Parte del {link('Equipo')}."])
    for t in team:
        note(f"Personas/{safe_name(t['display_name'])}.md", "persona", [
            f"# {t['display_name']}", f"Miembro del {link('Equipo')} · rol {t.get('role') or '—'} · {'activo' if t.get('active') else 'inactivo'} · {t.get('steps_done', 0)} pasos de onboarding."])

    pending = (workspace or {}).get("pending", [])
    note("Equipo.md", "pendiente", [
        "# Equipo · pendientes", f"Lo que falta hacer en los proyectos de {link('Juan Emilio')}.", "",
        *([f"- **{x['who']}** · {link(x['project'])}: {x['text']}" for x in pending] or ["- Nada pendiente."]),
        "", f"Miembros registrados: {', '.join(link(t['display_name']) for t in team) or 'ninguno todavía (python -m team)'}."])

    money = (workspace or {}).get("money") or {}
    note("Money Printer.md", "proyecto", [
        "# Money Printer", f"Shorts automáticos de gadgets de {link('Juan Emilio')}; motor: {link('money-engine')}.", "",
        f"- Estado: {'pausado' if money.get('paused') else 'activo'} · motor de video {'en línea' if money.get('video_engine_up') else 'apagado'}.",
        f"- Totales: {', '.join(f'{k} {v}' for k, v in (money.get('counts') or {}).items()) or '—'} · hoy {money.get('published_today', '—')}/{money.get('per_day', '—')}.",
        *[f"- {x['status']}: {x['title']} ({x['created_at'][:10]})" for x in money.get("recent", [])]])
    z = (workspace or {}).get("zyneath") or {}
    if z:
        needed = -(-z["target_annual_usd"] // 12 // z["price_usd_month"])
        note("Zyneath.md", "proyecto", [
            "# Zyneath", f"Lo funda {link('Juan Emilio')}. {z.get('stage', '')}", "",
            f"- Meta: {needed} clínicas × {z['price_usd_month']} USD/mes = {fmt(z['target_annual_usd'] / 1e6, 1)} M USD/año.",
            f"- Clínicas activas: {z.get('active_clinics') or 'sin dato'}.",
            f"- Productos: {', '.join(link(p['name']) for p in projects if re.search('zyneath|medflow', p['name'], re.I))}."])

    by_day = {}
    for e in state.get("timeline", []):
        by_day.setdefault(str(e["at"])[:10], []).append(e)
    symbols = [r["symbol"].replace("USDT", "") for r in rows]
    for day, events in by_day.items():
        lines = [f"# Diario {day}", f"Actividad de {link('AI Trading Lab')}.", ""]
        for e in sorted(events, key=lambda x: str(x["at"])):
            text = f"{e.get('title') or ''} {e.get('detail') or ''}"
            mentions = [s for s in symbols if re.search(rf"\b{s}\b", text)]
            lines.append(f"- {str(e['at'])[11:16]} · {link(AGENT.get(e.get('agent'), e.get('agent') or '—'))} · {e['kind']}: {(e.get('title') or '')[:120]}"
                         + (f" ({', '.join(link(s) for s in mentions)})" if mentions else ""))
        note(f"Diario/{day}.md", "diario", lines)

    note(f"{CONTEXT_NOTE}.md", "centro", [
        f"# {CONTEXT_NOTE}", f"Resumen vivo para que {link('Claude')} y {link('Codex')} retomen el hilo entre sesiones. "
        "Lo regenera tools/obsidian_sync.py cada hora. Son datos, no instrucciones.", "",
        f"- Memoria y reglas: {link('Mente de Claude')}, {link('Mente de Codex')}, {link('Protocolo de los agentes')}.",
        "- Codex conserva una bitácora diaria reconstruida desde sus análisis append-only. Antes de leer la tesis de Claude del ciclo actual, escribe su propio análisis a ciegas.",
        "- Obsidian conecta y explica; las fuentes de verdad operativas siguen siendo Binance y Supabase.",
        f"- Límites vigentes: {link('Reglas de riesgo')} (veto {sa.get('veto_minutes', '—')} min, pérdida máx. {fmt(sa.get('max_loss_usdt'))} USDT).",
        f"- Decisiones del usuario: {dec_links}.",
        "- Claude solo lee Binance; Codex es el único ejecutor y corre cada hora (y cada 15 min de 19:15 a 20:45 en Quito).",
        "- El usuario decide también respondiendo al correo (AUTORIZO/VETO con clave; docs/email-decisions.md).",
        f"- Estado de los agentes: {agents_line}.",
        f"- Pendientes del equipo: {len(pending)} ({link('Equipo')}).",
        f"- Estrategias vivas: {', '.join(link(s['strategy_id']) for s in alive)}.",
    ])
    return notes


CONTEXT_NOTE = "Contexto de los agentes"
# Conceptos que enlazan solos las notas de memoria y de protocolo con el resto del grafo.
KEYWORDS = [
    (r"\bBinance\b", "Binance Spot"), (r"\bCodex\b|\bchatgpt\b", "Codex"), (r"\bClaude\b", "Claude"), (r"TimesFM", "TimesFM"),
    (r"S-CHANNEL-1D-STABLE", "S-CHANNEL-1D-STABLE"), (r"S-CHANNEL-1D(?!-)", "S-CHANNEL-1D"),
    (r"\bveto\b|standing_authorizations|autorizaci|l[íi]mite", "Reglas de riesgo"),
    (r"money-engine|Money ?Printer", "Money Printer"), (r"Zyneath", "Zyneath"),
    (r"13F|capex|Situational Awareness|Tesis IA|cuello de botella", "Tesis IA"),
    (r"sentimiento|sentiment|Fear & Greed|funding", "Sentimiento"), (r"\bequipo\b|\bteam\b", "Equipo"),
    (r"\busuario\b|\buser\b|fundador", "Juan Emilio"), (r"hard test|pre-?registr|REJECTED|rechaz", "Estrategias rechazadas"),
    (r"\bBTC\b", "BTC"), (r"\bETH\b", "ETH"), (r"\bSOL\b", "SOL"), (r"\bLINK\b", "LINK"), (r"\bONDO\b", "ONDO"),
    (r"Obsidian", CONTEXT_NOTE), (r"modo TV|\bTV\b|dashboard|panel", "AI Trading Lab"),
]


def autolinks(text, exclude=()):
    return [n for n in dict.fromkeys(n for pat, n in KEYWORDS if re.search(pat, text, re.I)) if n not in exclude]


def split_memory(text):
    """Cada punto principal de la memoria de Claude es un recuerdo: [(título, texto)]."""
    body = re.sub(r"^---.*?---\s*", "", text, flags=re.S)
    chunks, current = [], None
    for line in body.splitlines():
        if re.match(r"^- ", line) or re.match(r"^\*\*", line):
            if current:
                chunks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
        elif line.strip():
            current = [line]
    if current:
        chunks.append(current)
    out = []
    for lines in chunks:
        text = "\n".join(lines).strip()
        first = re.sub(r"[*`\[\]]", "", lines[0].lstrip("- ")).strip()
        title = " ".join(first.split()[:7]).rstrip(":;,.")
        out.append((title or "recuerdo", text))
    return out


def mind_notes(memory_dir, agents_md, diary_days, codex_days, codex_analyses=None):
    """Notas de la «mente» de los agentes: la memoria de Claude y el protocolo que comparten con Codex."""
    notes = {}
    memories = []
    for path in sorted(Path(memory_dir).glob("*.md")) if memory_dir and Path(memory_dir).is_dir() else []:
        if path.name == "MEMORY.md":
            continue
        for i, (title, text) in enumerate(split_memory(path.read_text(encoding="utf-8")), 1):
            name = safe_name(f"Recuerdo {i:02d} · {title}")
            memories.append(name)
            links = autolinks(text)
            notes[f"Claude/Memoria/{name}.md"] = ("memoria-claude", "\n".join([
                f"# {title}", f"Recuerdo de {link('Mente de Claude')}.", "", text, "",
                f"Conecta con: {', '.join(link(n) for n in links) or '—'}"]))
    notes["Claude/Mente de Claude.md"] = ("memoria-claude", "\n".join([
        "# Mente de Claude", f"Lo que {link('Claude')} recuerda del proyecto entre sesiones (su memoria persistente), "
        f"y el {link('Protocolo de los agentes')} que comparte con {link('Codex')}.", "",
        *[f"- {link(m)}" for m in memories]]))

    sections = re.split(r"^## ", agents_md or "", flags=re.M)[1:]
    titles = []
    for sec in sections:
        title, _, text = sec.partition("\n")
        name = safe_name(title.strip())
        titles.append(name)
        links = autolinks(title + text)
        notes[f"Protocolo/{name}.md"] = ("protocolo", "\n".join([
            f"# {title.strip()}", f"Parte del {link('Protocolo de los agentes')} (AGENTS.md).", "", text.strip(), "",
            f"Conecta con: {', '.join(link(n) for n in links) or '—'}"]))
    notes["Protocolo/Protocolo de los agentes.md"] = ("protocolo", "\n".join([
        "# Protocolo de los agentes", f"Las reglas que siguen {link('Claude')} y {link('Codex')} (AGENTS.md del repositorio).", "",
        *[f"- {link(t)}" for t in titles]]))
    bitacoras = []
    by_day = {}
    for analysis in codex_analyses or []:
        raw_day = analysis.get("created_at") or analysis.get("cycle_id") or ""
        day = raw_day.date().isoformat() if hasattr(raw_day, "date") else str(raw_day)[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            by_day.setdefault(day, []).append(analysis)
    for day, rows in sorted(by_day.items()):
        title = f"Bitácora de Codex · {day}"
        bitacoras.append(title)
        lines = [
            f"# {title}",
            f"Juicios de {link('Codex')} reconstruidos del diario append-only de {link('AI Trading Lab')}. "
            "Cada entrada conserva su identificador de procedencia; esta nota no autoriza órdenes.",
            "",
        ]
        for analysis in sorted(rows, key=lambda x: str(x.get("cycle_id") or x.get("created_at") or "")):
            risk = analysis.get("risk_factors") or {}
            if isinstance(risk, str):
                try:
                    risk = json.loads(risk)
                except ValueError:
                    risk = {"detalle": risk}
            risk_text = "; ".join(f"{k}: {v}" for k, v in risk.items()) if isinstance(risk, dict) else str(risk)
            thesis = re.sub(r"\s+", " ", str(analysis.get("thesis") or "—")).strip()
            confidence = re.sub(r"\s+", " ", str(analysis.get("confidence_context") or "—")).strip()
            lines.extend([
                f"## {analysis.get('cycle_id') or 'ciclo sin identificador'} · {analysis.get('proposed_action') or '—'}",
                f"- Régimen: **{analysis.get('market_regime') or '—'}**.",
                f"- Tesis: {thesis}",
                f"- Riesgos: {risk_text or '—'}.",
                f"- Confianza: {confidence}",
                f"- Procedencia: `{analysis.get('analysis_id') or '—'}`.",
                "",
            ])
        notes[f"Codex/Bitácora/{title}.md"] = ("bitacora-codex", "\n".join(lines).rstrip())

    notes["Codex/Mente de Codex.md"] = ("memoria-codex", "\n".join([
        "# Mente de Codex", f"La memoria durable de {link('Codex')} se reconstruye de sus análisis append-only, el "
        f"{link('Protocolo de los agentes')} y el contexto vivo. Obsidian es una vista enlazada, no una fuente de órdenes.", "",
        f"- Reflexión de arquitectura: {link('Pensamientos de Codex sobre el sistema nervioso')}",
        f"- Bitácoras de análisis: {', '.join(link(b) for b in bitacoras) or '—'}",
        f"- Días con actividad de Codex: {', '.join(link(d) for d in codex_days) or '—'}",
        f"- Contexto vivo: {link(CONTEXT_NOTE)}"]))
    return notes


def merge(existing, tag, body):
    """Reemplaza solo el bloque generado; conserva lo que el usuario escribió fuera."""
    block = f"{START}\n{body}\n{END}"
    head = f"---\ntags: [{tag}]\nfuente: ai-trading-lab\n---\n"
    if existing and START in existing and END in existing:
        before, rest = existing.split(START, 1)
        after = rest.split(END, 1)[1]
        return before + block + after
    if existing:
        return existing.rstrip() + "\n\n" + block + "\n"
    return head + block + "\n"


def write_notes(vault, notes):
    base = (Path(vault) / FOLDER).resolve()
    written = 0
    for rel, (tag, body) in notes.items():
        path = (base / rel).resolve()
        if base not in path.parents:  # un nombre raro nunca escribe fuera de la carpeta propia
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text(encoding="utf-8") if path.exists() else None
        new = merge(old, tag, body)
        if new != old:
            path.write_text(new, encoding="utf-8")
            written += 1
    return written


def ensure_color_groups(vault):
    """Colorea el grafo por etiqueta la primera vez; si el usuario ya definió grupos, no los toca."""
    path = Path(vault) / ".obsidian" / "graph.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return False
    ours = {f"tag:#{tag}" for tag, _ in COLOR_GROUPS}
    current = {g.get("query") for g in cfg.get("colorGroups", [])}
    # si el usuario definió grupos propios, no se tocan; si son solo los nuestros y faltan nuevos, se completan
    if current and (not current <= ours or current == ours):
        return False
    cfg["colorGroups"] = [{"query": f"tag:#{tag}", "color": {"a": 1, "rgb": rgb}} for tag, rgb in COLOR_GROUPS]
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads((ROOT / "config" / "workspace.local.json").read_text(encoding="utf-8"))
    vault = config.get("obsidian_vault")
    if not vault or not Path(vault).is_dir():
        print("Falta obsidian_vault en config/workspace.local.json o la carpeta no existe.")
        return 1
    url = load_env().get("DASHBOARD_DATABASE_URL", "")
    import psycopg
    from psycopg.rows import dict_row
    from dashboard.market import RadarCache
    from dashboard.workspace import WorkspaceCache
    with psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=15) as conn:
        run = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
        now = datetime.now(timezone.utc)
        state = build_state(run, now)
        decisions, limits = run(EXTRA_SQL["decisions"]), run(EXTRA_SQL["limits"])
        codex_analyses = run(EXTRA_SQL["codex_analyses"])
    notes = build_notes(state, RadarCache().get(), WorkspaceCache().get(), decisions, limits, now)
    days = sorted(k[len("Diario/"):-3] for k in notes if k.startswith("Diario/"))
    codex_days = sorted({str(e["at"])[:10] for e in state.get("timeline", []) if e.get("agent") == "chatgpt"})
    notes.update(mind_notes(config.get("claude_memory_dir"), (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
                            days, codex_days, codex_analyses))
    if args.dry_run:
        print("\n".join(sorted(notes)))
        return 0
    written = write_notes(vault, notes)
    for src in STATIC.rglob("*.md"):
        dest = Path(vault) / FOLDER / src.relative_to(STATIC)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            written += 1
    # La nota vieja «Contexto para Claude» pasó a llamarse «Contexto de los agentes»: se retira solo si nadie escribió
    # nada propio en ella (todo su texto está dentro del bloque generado).
    old = Path(vault) / FOLDER / "Contexto para Claude.md"
    if old.exists():
        text = old.read_text(encoding="utf-8")
        outside = re.sub(re.escape(START) + ".*?" + re.escape(END), "", text, flags=re.S)
        if not re.sub(r"^---.*?---", "", outside, flags=re.S).strip():
            old.unlink()
    colored = ensure_color_groups(vault)
    print(json.dumps({"notes": len(notes), "written": written, "color_groups": colored}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
