"""Radar de memecoins de Solana: descubre, describe, puntúa y mide sus propias alertas. Solo lectura de datos públicos.

  C:\\Python314\\pythonw.exe tools\\meme_radar.py      (tarea «AI Trading Lab\\Radar memecoins», cada 15 minutos)
  python -m tools.meme_radar --dry-run               (todo menos escribir en el diario; imprime el tablero)
  python -m tools.meme_radar --token <dirección>     (ficha de un token, sin escribir nada)

Fuentes gratuitas, sin cuenta: perfiles y boosts de DexScreener, pools en tendencia y nuevos de GeckoTerminal, tokens
nuevos de RugCheck y un único RSS combinado de los subreddits de config/memecoins.json (Reddit corta si se le piden
varios seguidos). Para cada candidato: mercado (DexScreener) y seguridad e insiders (RugCheck). Guarda la foto en
meme_snapshots (rol lab_ingest), crea una alerta si hay mucha atención con seguridad limpia y mide las alertas
vencidas a 1 h, 24 h y 7 días. Nunca toca una billetera ni pide claves. Ninguna salida es una recomendación de compra.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pythonw lo lanza como script, sin -m
    sys.path.insert(0, str(ROOT))

from ai_trading_lab import memecoins as mc  # noqa: E402
from dashboard.config import load_env  # noqa: E402

UA = {"User-Agent": "ai-trading-lab/1.0 (personal research; meme radar)", "Accept": "application/json, */*"}
OUT = ROOT / "data" / "raw" / "memes"
BUDGET_SECONDS = 600
ATOM = "{http://www.w3.org/2005/Atom}"
DEX_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_BOOSTS = ("https://api.dexscreener.com/token-boosts/top/v1", "https://api.dexscreener.com/token-boosts/latest/v1")
DEX_TOKENS = "https://api.dexscreener.com/tokens/v1/solana/{}"
GECKO = {"gecko_trending": "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools",
         "gecko_new": "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"}
RUG_NEW = "https://api.rugcheck.xyz/v1/stats/new_tokens"
RUG_REPORT = "https://api.rugcheck.xyz/v1/tokens/{}/report"
REDDIT = "https://www.reddit.com/r/{}/new/.rss?limit=100"


def log(line):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "log.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ} {line}\n")


def fetch(url, attempts=3, as_json=True):
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                body = r.read().decode("utf-8", "replace")
                return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < attempts:  # límite de la API: esperar y reintentar
                time.sleep(5 * attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)


def reddit_entries(subs):
    xml = fetch(REDDIT.format("+".join(subs)), as_json=False)
    root = ET.fromstring(xml)
    out = []
    for e in root.iter(f"{ATOM}entry"):
        text = " ".join(filter(None, [e.findtext(f"{ATOM}title"), e.findtext(f"{ATOM}content")]))
        published = e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated")
        if published:
            out.append((text, datetime.fromisoformat(published.replace("Z", "+00:00"))))
    return out


def discover(config, errors):
    """[(mint, fuente)] y las menciones de Reddit. Una fuente caída queda en errors y no detiene el resto."""
    found = [(w["mint"], "watchlist") for w in config.get("watchlist", []) if mc.is_mint(w.get("mint"))]

    def attempt(name, fn):
        try:
            return fn()
        except Exception as e:  # una fuente rota no debe tumbar la corrida
            errors.append(f"{name}: {type(e).__name__}")
            return []

    found += attempt("dexscreener perfiles", lambda: mc.mints_from_dexscreener(fetch(DEX_PROFILES)))
    for url in DEX_BOOSTS:
        found += attempt("dexscreener boosts", lambda: mc.mints_from_dexscreener(fetch(url)))
    for name, url in GECKO.items():
        found += attempt(name, lambda: mc.mints_from_gecko(fetch(url), name))
    found += attempt("rugcheck nuevos", lambda: mc.mints_from_rugcheck(fetch(RUG_NEW)))
    entries = attempt("reddit", lambda: reddit_entries(config.get("subreddits", ["solana"])))
    addresses, tickers = mc.reddit_mentions(entries)
    found += [(a, "reddit") for a in addresses]
    return found, addresses, tickers


def market(mints):
    """Mejor par de cada token, de 30 en 30 (límite de DexScreener por pedido)."""
    pairs = {}
    mints = list(mints)
    for i in range(0, len(mints), 30):
        for p in fetch(DEX_TOKENS.format(",".join(mints[i:i + 30]))) or []:
            pairs.setdefault((p.get("baseToken") or {}).get("address"), []).append(p)
    return {m: mc.best_pair(ps) for m, ps in pairs.items() if m}


def build(config, now, deadline, errors, only=None):
    if only:
        candidates, addresses, tickers = {only: {"manual"}}, {}, {}
    else:
        found, addresses, tickers = discover(config, errors)
        candidates = {}
        for mint, source in found:
            candidates.setdefault(mint, set()).add(source)
    pairs = market(list(candidates)[:150])
    watch = {w["mint"] for w in config.get("watchlist", [])} | ({only} if only else set())
    rows = []
    for mint, sources in candidates.items():
        pair = pairs.get(mint)
        if not pair:
            continue
        row = {"mint": mint, "sources": sorted(sources), **mc.market_from_pair(pair)}
        row["mentions_6h"] = mc.count_mentions(mint, row["symbol"], addresses, tickers, now)
        row["attention_score"], _ = mc.attention_score(row)
        rows.append(row)
    # RugCheck es lo caro: solo los que tienen liquidez real, por atención, y siempre la lista de seguimiento.
    floor = config.get("min_liquidity_usd", 10_000)
    ranked = sorted((r for r in rows if r["mint"] in watch or (r.get("liquidity_usd") or 0) >= floor),
                    key=lambda r: (r["mint"] not in watch, -r["attention_score"]))
    out = []
    for row in ranked[:config.get("max_rugcheck_per_run", 25) + len(watch)]:
        if time.monotonic() > deadline:
            errors.append("tiempo agotado antes de revisar todos los candidatos")
            break
        try:
            report = fetch(RUG_REPORT.format(row["mint"]))
        except Exception as e:
            errors.append(f"rugcheck {row['symbol']}: {type(e).__name__}")
            continue
        finally:
            time.sleep(1.1)  # RugCheck gratis: un informe por segundo
        row.update(mc.safety_from_rugcheck(report, row.get("pair_address")))
        row["risk_score"], risk_flags = mc.risk_score(row, now)
        row["attention_score"], att_flags = mc.attention_score(row)
        row["flags"] = risk_flags + att_flags
        row["observed_at"] = now
        out.append(row)
    return out


# ---------------------------------------------------------------- diario
SNAP_COLS = ("mint", "symbol", "name", "pair_address", "dex", "observed_at", "pair_created_at", "price_usd",
             "market_cap_usd", "liquidity_usd", "volume_h1", "volume_h24", "buys_h1", "sells_h1", "price_change_h1",
             "price_change_h24", "holders", "top10_pct", "mint_revoked", "freeze_revoked", "lp_locked_pct",
             "insider_networks", "insider_wallets", "insider_supply_pct", "creator_pct", "rugcheck_score", "risks", "mentions_6h", "sources", "attention_score",
             "risk_score", "flags", "links")


def write(rows, now, reader_url, ingest_url):
    import psycopg
    from psycopg.types.json import Jsonb
    with psycopg.connect(reader_url, autocommit=True, prepare_threshold=None, connect_timeout=15) as rd:
        last = dict(rd.execute("select mint, max(alerted_at) from meme_alerts group by mint").fetchall())
        pending = [{"id": i, "mint": m, "alerted_at": t, "price_usd": float(p)} for i, m, t, p in rd.execute(
            "select id, mint, alerted_at, price_usd from meme_alerts where alerted_at > now() - interval '8 days'").fetchall()]
        done = set(rd.execute("select alert_id, horizon_hours from meme_alert_outcomes").fetchall())
    alerts, outcomes = [], []
    with psycopg.connect(ingest_url, autocommit=True, prepare_threshold=None, connect_timeout=15) as wr:
        for r in rows:
            values = [Jsonb(r.get(c) or ([] if c == "risks" else {})) if c in ("risks", "links") else r.get(c) for c in SNAP_COLS]
            sid = wr.execute(f"insert into meme_snapshots ({', '.join(SNAP_COLS)}, scorer_version, recorded_by_agent_id) "
                             f"values ({', '.join(['%s'] * len(SNAP_COLS))}, %s, 'claude') returning id",
                             [*values, mc.SCORER_VERSION]).fetchone()[0]
            reason = mc.should_alert(r, last.get(r["mint"]), now)
            if reason:
                wr.execute("insert into meme_alerts (snapshot_id, mint, alerted_at, price_usd, attention_score, risk_score, "
                           "reason, scorer_version, recorded_by_agent_id) values (%s, %s, %s, %s, %s, %s, %s, %s, 'claude')",
                           [sid, r["mint"], now, r["price_usd"], r["attention_score"], r["risk_score"], reason, mc.SCORER_VERSION])
                alerts.append(f"{r['symbol']} ({r['mint']}): {reason}")
        due = mc.outcomes_due(pending, done, now)
        if due:
            pairs = market({a["mint"] for a, _ in due})
            for a, h in due:
                res = mc.outcome_return(a["price_usd"], pairs.get(a["mint"]))
                wr.execute("insert into meme_alert_outcomes (alert_id, horizon_hours, price_usd, liquidity_usd, return_pct, "
                           "recorded_by_agent_id) values (%s, %s, %s, %s, %s, 'claude') on conflict do nothing",
                           [a["id"], h, res["price_usd"], res["liquidity_usd"], res["return_pct"]])
                outcomes.append((a["mint"], h, res["return_pct"]))
    return alerts, outcomes


def table(rows):
    lines = [f"{'token':<14}{'capitaliz.':>13}{'liquidez':>11}{'vol 1h':>10}{'atención':>9}{'riesgo':>8}  banderas"]
    for r in sorted(rows, key=lambda r: -r["attention_score"]):
        lines.append(f"{(r['symbol'] or '?')[:13]:<14}{r.get('market_cap_usd') or 0:>13,.0f}{r.get('liquidity_usd') or 0:>11,.0f}"
                     f"{r.get('volume_h1') or 0:>10,.0f}{r['attention_score']:>9.0f}{r['risk_score']:>8.0f}  {'; '.join(r['flags'][:4])}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--token", help="ficha de un token por su dirección (no escribe nada)")
    args = parser.parse_args(argv)
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    if args.token and not mc.is_mint(args.token):
        print("Dirección de token no válida.")
        return 2
    started, now, errors = time.monotonic(), datetime.now(timezone.utc), []
    config = json.loads((ROOT / "config" / "memecoins.json").read_text(encoding="utf-8"))
    rows = build(config, now, started + BUDGET_SECONDS, errors, only=args.token)
    if args.token:
        print(json.dumps(rows[0] if rows else {"error": "sin par en DexScreener"}, ensure_ascii=False, indent=1, default=str))
        return 0
    if args.dry_run:
        print(table(rows))
        print("errores:", errors)
        return 0
    env = load_env()
    alerts, outcomes = write(rows, now, env.get("DASHBOARD_DATABASE_URL", ""), env.get("INGEST_DATABASE_URL", ""))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ultima.json").write_text(json.dumps({"hora": now.isoformat(), "fotos": len(rows), "alertas": alerts,
                                                  "resultados": outcomes, "errores": errors}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    log(f"{len(rows)} fotos, {len(alerts)} alerta(s), {len(outcomes)} resultado(s), {len(errors)} error(es), "
        f"{time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
