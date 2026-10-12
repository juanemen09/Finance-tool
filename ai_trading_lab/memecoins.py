"""Radar de memecoins de Solana: lógica pura (sin red) para descubrir, describir y puntuar tokens.

Dos puntuaciones separadas, de 0 a 100, porque responden preguntas distintas:
- atención: ¿está entrando gente ahora? (volumen frente a liquidez, presión compradora, transacciones, Reddit);
- riesgo: ¿puede el creador o un grupo de billeteras dejarte sin salida? (permisos, liquidez, concentración, insiders).
Los umbrales son una hipótesis a priori. La prueba hacia delante (meme_alert_outcomes) dice si sirven: cambiar una
fórmula o un umbral es otra SCORER_VERSION y se mide aparte. Nada de esto es una recomendación de compra.
"""
import re
from datetime import datetime, timedelta, timezone

SCORER_VERSION = "meme-v2"  # v2 (2026-10-12): sin alerta si el volumen parece de bots
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
ADDRESS_IN_TEXT = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
TICKER_IN_TEXT = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,11})\b")
QUOTES = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
          "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}  # SOL, USDC y USDT: no son memecoins

# Alerta: mucha atención con seguridad limpia, y todavía chica (lo grande ya no es "el próximo").
ALERT = {"min_attention": 60, "max_risk": 30, "min_liquidity_usd": 20_000, "max_market_cap_usd": 50_000_000,
         "cooldown_hours": 24, "min_age_hours": 1}
HORIZONS = (1, 24, 168)


def is_mint(text):
    return bool(text) and bool(MINT_RE.match(text)) and text not in QUOTES


# ---------------------------------------------------------------- descubrimiento
def mints_from_dexscreener(items):
    """token-profiles y token-boosts de DexScreener: [(mint, fuente)]."""
    out = []
    for it in items or []:
        if it.get("chainId") == "solana" and is_mint(it.get("tokenAddress")):
            out.append((it["tokenAddress"], "dexscreener_boost" if "totalAmount" in it or "amount" in it else "dexscreener_profile"))
    return out


def mints_from_gecko(payload, source):
    """Pools de GeckoTerminal: el token base viene como 'solana_<mint>'."""
    out = []
    for pool in (payload or {}).get("data", []):
        base = (((pool.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id", "")
        mint = base.removeprefix("solana_")
        if is_mint(mint):
            out.append((mint, source))
    return out


def mints_from_rugcheck(items):
    return [(it["mint"], "rugcheck_new") for it in items or [] if is_mint(it.get("mint"))]


def reddit_mentions(entries):
    """entries: [(texto, publicado)]. Devuelve (direcciones mencionadas, tickers mencionados) con la hora de cada mención."""
    addresses, tickers = {}, {}
    for text, published in entries:
        for a in set(ADDRESS_IN_TEXT.findall(text or "")):
            if is_mint(a):
                addresses.setdefault(a, []).append(published)
        for t in set(TICKER_IN_TEXT.findall(text or "")):
            tickers.setdefault(t.upper(), []).append(published)
    return addresses, tickers


def count_mentions(mint, symbol, addresses, tickers, now, hours=6):
    since = now - timedelta(hours=hours)
    hits = [t for t in addresses.get(mint, []) if t >= since]
    if symbol and len(symbol) >= 3:  # "$AI" o "$GO" chocan con demasiadas cosas
        hits += [t for t in tickers.get(symbol.upper().lstrip("$"), []) if t >= since]
    return len(hits)


# ---------------------------------------------------------------- descripción
def best_pair(pairs):
    """El par de Solana con más liquidez (ahí se forma el precio)."""
    sol = [p for p in pairs or [] if p.get("chainId") == "solana"]
    return max(sol, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, default=None)


def market_from_pair(p):
    txh1 = (p.get("txns") or {}).get("h1") or {}
    info = p.get("info") or {}
    created = p.get("pairCreatedAt")
    return {
        "symbol": ((p.get("baseToken") or {}).get("symbol") or "")[:40],
        "name": ((p.get("baseToken") or {}).get("name") or "")[:120],
        "pair_address": p.get("pairAddress") if is_mint(p.get("pairAddress")) else None,
        "dex": (p.get("dexId") or "")[:40],
        "pair_created_at": datetime.fromtimestamp(created / 1000, timezone.utc) if created else None,
        "price_usd": _num(p.get("priceUsd")),
        "market_cap_usd": _num(p.get("marketCap") or p.get("fdv")),
        "liquidity_usd": _num((p.get("liquidity") or {}).get("usd")),
        "volume_h1": _num((p.get("volume") or {}).get("h1")),
        "volume_h24": _num((p.get("volume") or {}).get("h24")),
        "buys_h1": int(txh1.get("buys") or 0),
        "sells_h1": int(txh1.get("sells") or 0),
        "price_change_h1": _signed((p.get("priceChange") or {}).get("h1")),
        "price_change_h24": _signed((p.get("priceChange") or {}).get("h24")),
        "boosted": bool((p.get("boosts") or {}).get("active")),
        "links": {"dexscreener": p.get("url") if str(p.get("url", "")).startswith("https://") else None,
                  "web": [w.get("url") for w in info.get("websites", []) if str(w.get("url", "")).startswith("https://")][:2],
                  "redes": [s.get("url") for s in info.get("socials", []) if str(s.get("url", "")).startswith("https://")][:4]},
    }


def safety_from_rugcheck(report, pair_address=None):
    """Seguridad en cadena desde el informe de RugCheck. La concentración excluye el pool, el AMM y el creador
    (cuentas conocidas), que no son holders que puedan vender en tu contra de la misma forma."""
    if not report:
        return {}
    known = set((report.get("knownAccounts") or {}).keys()) | {pair_address}
    known |= {m.get("pubkey") for m in report.get("markets") or []}
    holders = report.get("topHolders") or []
    free = [h for h in holders if h.get("owner") not in known and h.get("address") not in known]
    lp = [((m.get("lp") or {}).get("lpLockedPct")) for m in report.get("markets") or []]
    lp = [x for x in lp if x is not None]
    supply = ((report.get("token") or {}).get("supply")) or 0
    creator_balance = report.get("creatorBalance") or 0
    networks = report.get("insiderNetworks") or []
    # Lo que controlan ahora las redes de billeteras conectadas (se transfirieron entre sí): el dato de "insiders".
    insider_raw = sum(int(n.get("currentHolding") or 0) for n in networks)
    return {
        "holders": report.get("totalHolders"),
        "top10_pct": round(min(100.0, sum(h.get("pct") or 0 for h in free[:10])), 2),
        "insider_holder_pct": round(sum(h.get("pct") or 0 for h in holders if h.get("insider")), 2),
        "mint_revoked": report.get("mintAuthority") in (None, ""),
        "freeze_revoked": report.get("freezeAuthority") in (None, ""),
        "lp_locked_pct": round(max(lp), 2) if lp else None,
        "insider_networks": len(networks),
        "insider_wallets": int(report.get("graphInsidersDetected") or 0),
        "insider_supply_pct": round(min(100.0, insider_raw / supply * 100), 2) if supply else None,
        "creator_pct": round(min(100.0, creator_balance / supply * 100), 2) if supply else None,
        "rugcheck_score": report.get("score_normalised", report.get("score")),
        "rugged": bool(report.get("rugged")),
        "risks": [{"name": (r.get("name") or "")[:80], "level": r.get("level")} for r in report.get("risks") or []][:12],
    }


# ---------------------------------------------------------------- puntuaciones
def risk_score(s, now):
    """0 = limpio, 100 = trampa probable. Devuelve (puntuación, banderas)."""
    score, flags = 0.0, []

    def add(points, flag):
        nonlocal score
        score += points
        flags.append(flag)

    if s.get("rugged"):
        add(100, "rug detectado")
    if s.get("mint_revoked") is False:
        add(35, "el creador puede imprimir más")
    if s.get("freeze_revoked") is False:
        add(35, "el creador puede congelar billeteras")
    lp = s.get("lp_locked_pct")
    if lp is None:
        add(10, "liquidez bloqueada: sin dato")
    elif lp < 90:
        add(20, f"solo {lp:.0f} % de la liquidez bloqueada")
    top10 = s.get("top10_pct")
    if top10 is not None and top10 > 50:
        add(25, f"top 10 tiene {top10:.0f} %")
    elif top10 is not None and top10 > 30:
        add(12, f"top 10 tiene {top10:.0f} %")
    ins = s.get("insider_supply_pct") or 0
    nets, wallets = s.get("insider_networks") or 0, s.get("insider_wallets") or 0
    if ins > 95:  # visto en tokens grandes (W): RugCheck suma tesorerías o pools; no es creíble como insiders
        add(15, f"dato de insiders dudoso ({ins:.0f} %, {wallets} billeteras): revisar a mano")
    elif ins > 30:
        add(30, f"insiders controlan {ins:.0f} % ({nets} redes, {wallets} billeteras)")
    elif ins > 10:
        add(15, f"insiders controlan {ins:.0f} % ({nets} redes, {wallets} billeteras)")
    elif ins > 3:
        add(5, f"insiders con {ins:.0f} %")
    if (s.get("insider_holder_pct") or 0) > 10:
        add(10, f"insiders con {s['insider_holder_pct']:.0f} %")
    if (s.get("creator_pct") or 0) > 5:
        add(10, f"el creador conserva {s['creator_pct']:.0f} %")
    dangers = sum(1 for r in s.get("risks") or [] if r.get("level") == "danger")
    if dangers:
        add(min(24, 8 * dangers), f"{dangers} riesgo(s) graves en RugCheck")
    liq, mcap = s.get("liquidity_usd") or 0, s.get("market_cap_usd") or 0
    if liq < 10_000:
        add(10, "liquidez < 10 000 USD")
    if mcap and liq / mcap < 0.05:
        add(10, "liquidez < 5 % de la capitalización")
    created = s.get("pair_created_at")
    if created and now - created < timedelta(hours=1):
        add(15, "par con menos de 1 h")
    elif created and now - created < timedelta(hours=6):
        add(5, "par con menos de 6 h")
    if mcap and (s.get("volume_h1") or 0) > 3 * mcap:
        add(20, "volumen de 1 h > 3 veces la capitalización: posible volumen de bots")
    return min(100.0, round(score, 1)), flags


def attention_score(s):
    """0 = nadie lo mira, 100 = entrada fuerte ahora. Devuelve (puntuación, banderas)."""
    liq = s.get("liquidity_usd") or 0
    mcap = s.get("market_cap_usd") or 0
    vol1 = s.get("volume_h1") or 0
    buys, sells = s.get("buys_h1") or 0, s.get("sells_h1") or 0
    tx = buys + sells
    score, flags = 0.0, []
    if liq:
        score += min(1.0, (vol1 / liq) / 0.5) * 30  # mover la mitad de la liquidez en una hora ya es mucho
    if tx >= 10:
        score += min(1.0, max(0.0, (buys / tx - 0.5) * 2)) * 15
    score += min(1.0, tx / 300) * 15
    score += min(1.0, max(0.0, (s.get("price_change_h1") or 0) / 50)) * 10
    m = s.get("mentions_6h") or 0
    score += min(1.0, m / 5) * 20
    if m:
        flags.append(f"{m} mención(es) en Reddit en 6 h")
    if mcap:
        score += min(1.0, (s.get("volume_h24") or 0) / mcap) * 5
    if s.get("boosted"):
        score += 5
        flags.append("promoción pagada en DexScreener")
    return min(100.0, round(score, 1)), flags


def should_alert(snap, last_alert_at, now):
    if not snap.get("price_usd"):
        return None
    if snap["attention_score"] < ALERT["min_attention"] or snap["risk_score"] > ALERT["max_risk"]:
        return None
    if (snap.get("liquidity_usd") or 0) < ALERT["min_liquidity_usd"]:
        return None
    if (snap.get("market_cap_usd") or 0) > ALERT["max_market_cap_usd"]:
        return None
    created = snap.get("pair_created_at")
    if created and now - created < timedelta(hours=ALERT["min_age_hours"]):
        return None
    if (snap.get("market_cap_usd") or 0) and (snap.get("volume_h1") or 0) > 3 * snap["market_cap_usd"]:
        return None  # volumen inflado: también infla la atención, así que no se puede creer
    if last_alert_at and now - last_alert_at < timedelta(hours=ALERT["cooldown_hours"]):
        return None
    return (f"atención {snap['attention_score']:.0f}/100 con riesgo {snap['risk_score']:.0f}/100; "
            f"liquidez {snap['liquidity_usd']:,.0f} USD, capitalización {snap.get('market_cap_usd') or 0:,.0f} USD")[:500]


def outcomes_due(alerts, done, now):
    """alerts: [{id, alerted_at}], done: {(alert_id, horizonte)}. Devuelve [(alerta, horizonte)] ya vencidos y sin medir."""
    return [(a, h) for a in alerts for h in HORIZONS
            if (a["id"], h) not in done and now >= a["alerted_at"] + timedelta(hours=h)]


def outcome_return(alert_price, pair):
    """Retorno desde la alerta. Sin par o sin liquidez, el token murió: -100 %."""
    price = _num((pair or {}).get("priceUsd"))
    liq = _num(((pair or {}).get("liquidity") or {}).get("usd"))
    if not price or not liq:
        return {"price_usd": price, "liquidity_usd": liq, "return_pct": -100.0}
    return {"price_usd": price, "liquidity_usd": liq, "return_pct": round(max(-100.0, (price / alert_price - 1) * 100), 4)}


def _signed(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        f = float(v)
        return f if f == f and f >= 0 else None
    except (TypeError, ValueError):
        return None
