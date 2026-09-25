"""Estado del laboratorio para el panel: consultas fijas (sin parámetros del navegador) y su forma final.

`run_query(sql) -> list[dict]` lo pone el servidor (conexión de solo lectura); aquí todo es probable sin base.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

STALE_MINUTES = 75  # ambos agentes escriben un análisis por hora
AGENTS = ("claude", "chatgpt")

SQL = {
    "portfolio": "select balances, open_orders, observed_at from v_latest_portfolio",
    "risk_limits": "select max_position_usdt, max_open_positions, universe, executor_agent_id from v_current_risk_limits",
    "standing": "select active, veto_minutes, max_loss_usdt, min_reward_risk, weekly_loss_limit_usdt, created_at "
                "from standing_authorizations order by id desc limit 1",
    "open_positions": "select trade_ref, symbol, entry_price, quantity, notional_usdt, stop, invalidation, executed_at "
                      "from v_open_positions",
    "pnl_7d": "select coalesce(sum(pnl_usdt), 0) as pnl_7d from trade_closures where closed_at > now() - interval '7 days'",
    "performance": "select * from v_performance",
    "open_events": "select id, agent_id, kind, severity, message, created_at from v_open_events order by id desc",
    "last_analyses": "select distinct on (agent_id) agent_id, analysis_id, cycle_id, proposed_action, symbol, "
                     "market_regime, confidence_context, risk_factors, details -> 'sentiment' as sentiment, created_at "
                     "from analyses order by agent_id, id desc",
    "activity": "select agent_id, max(at) as created_at from ("
                " select agent_id, created_at as at from analyses"
                " union all select from_agent_id, created_at from agent_messages"
                " union all select acked_by_agent_id, created_at from message_acks"
                " union all select reviewer_agent_id, created_at from risk_reviews"
                " union all select agent_id, created_at from portfolio_snapshots) x group by agent_id",
    "scoreboard": "select * from v_agent_scoreboard",
    "analyses_count": "select agent_id, count(*) as n from analyses group by agent_id",
    "strategies": "select strategy_id, name, status, status_reason, status_since, last_verdict, last_run_at "
                  "from v_strategy_board order by status_since desc",
    "signals": "select distinct on (strategy_id, symbol) strategy_id, symbol, signal, entry_price, stop, cycle_id, "
               "bar_close_time from strategy_signals order by strategy_id, symbol, id desc",
    "proposals": "select *, case when status not in ('EXECUTED', 'EXPIRED') "
                 "then auto_authorization_status(proposal_id, now()) end as auto "
                 "from v_proposal_status order by created_at desc limit 5",
    "sentiment": "select source, metric, symbol, value, label, observed_at from v_sentiment_latest",
    "tone": "select * from v_news_sentiment_24h order by items desc",
    "news": "select source, author, title, url, published_at, symbols, sentiment from news_items "
            "order by published_at desc limit 25",
    "themes": "select source, author, title, url, published_at, themes, sentiment from v_theme_news "
              "order by published_at desc limit 20",
    "rwa": "select value, observed_at from sentiment_observations where metric = 'rwa_tvl_usd' "
           "order by observed_at desc limit 60",
    "research": "select source, title, url, own_summary, created_at from strategy_sources order by id desc limit 8",
    "ai_thesis": "select kind, as_of, title, body, data, created_at from v_research_latest",
    "equity": "select observed_at, balances from portfolio_snapshots order by observed_at limit 2000",
    "timeline": "select * from ("
                " select created_at as at, 'analysis' as kind, agent_id as agent, coalesce(proposed_action, '') as title,"
                "  left(coalesce(market_regime, ''), 240) as detail, analysis_id as ref from analyses"
                " union all select created_at, 'message', from_agent_id, kind || ' → ' || to_agent_id, left(body, 240),"
                "  related_ref from agent_messages"
                " union all select created_at, 'review', reviewer_agent_id, verdict, left(reasoning, 240), proposal_id"
                "  from risk_reviews"
                " union all select created_at, 'proposal', agent_id, side || ' ' || symbol, left(thesis, 240),"
                "  proposal_id from trade_proposals"
                " union all select created_at, 'trade', executor_agent_id, side || ' ' || symbol,"
                "  left(coalesce(entry_thesis, ''), 240), trade_ref from trades"
                " union all select created_at, 'closure', recorded_by_agent_id, exit_reason,"
                "  left(coalesce(lessons, ''), 240), trade_ref from trade_closures"
                " union all select created_at, 'event', agent_id, severity || ' · ' || kind, left(message, 240),"
                "  related_ref from events"
                " union all select created_at, 'strategy', recorded_by_agent_id, strategy_id || ' → ' || status,"
                "  left(reason, 240), strategy_id from strategy_status_events"
                " union all select created_at, 'veto', recorded_by_agent_id, 'VETO', left(user_message_quote, 240),"
                "  proposal_id from user_vetoes"
                ") t order by at desc limit 60",
}


def to_jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def next_daily_close(now):
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)


def agent_health(activity_rows, now):
    last = {r["agent_id"]: r["created_at"] for r in activity_rows}
    out = []
    for agent in AGENTS:
        at = last.get(agent)
        if at is None:
            out.append({"agent_id": agent, "last_activity": None, "minutes_since": None, "state": "sin actividad"})
            continue
        minutes = int((now - at).total_seconds() // 60)
        out.append({"agent_id": agent, "last_activity": at, "minutes_since": minutes,
                    "state": "ok" if minutes <= STALE_MINUTES else "atrasado"})
    return out


def equity_curve(rows):
    """USDT libre + bloqueado por foto. Otros activos se señalan: el panel no inventa su valor."""
    points = []
    for r in rows:
        usdt = sum(float(b.get("free", 0)) + float(b.get("locked", 0)) for b in r["balances"] or []
                   if b.get("asset") == "USDT")
        others = sorted(b["asset"] for b in r["balances"] or []
                        if b.get("asset") != "USDT" and float(b.get("free", 0)) + float(b.get("locked", 0)) > 0)
        points.append({"t": r["observed_at"], "usdt": round(usdt, 8), "other_assets": others})
    return points


def build_state(run_query, now):
    q = {name: run_query(sql) for name, sql in SQL.items()}
    portfolio = q["portfolio"][0] if q["portfolio"] else None
    state = {
        "now": now,
        "next_daily_close": next_daily_close(now),
        "portfolio": portfolio,
        "risk_limits": q["risk_limits"][0] if q["risk_limits"] else None,
        "standing_authorization": q["standing"][0] if q["standing"] else None,
        "open_positions": q["open_positions"],
        "pnl_7d": q["pnl_7d"][0]["pnl_7d"] if q["pnl_7d"] else 0,
        "performance": q["performance"][0] if q["performance"] else None,
        "open_events": q["open_events"],
        "agents": agent_health(q["activity"], now),
        "last_analyses": {r["agent_id"]: r for r in q["last_analyses"]},
        "analyses_count": {r["agent_id"]: r["n"] for r in q["analyses_count"]},
        "scoreboard": q["scoreboard"],
        "strategies": q["strategies"],
        "signals": q["signals"],
        "proposals": q["proposals"],
        "sentiment": {"latest": q["sentiment"], "tone_24h": q["tone"]},
        "news": q["news"],
        "research": q["research"],
        "ai_thesis": {r["kind"]: r for r in q["ai_thesis"]},
        "themes": q["themes"],
        "rwa": q["rwa"],
        "equity": equity_curve(q["equity"]),
        "timeline": q["timeline"],
    }
    return to_jsonable(state)
