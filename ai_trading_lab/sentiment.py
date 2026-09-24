"""Sentimiento del mercado: indicadores numéricos y titulares, listos para el diario.

Solo transforma datos ya descargados (lo prueba todo sin red); la descarga está en tools/ingest_sentiment.py.
Ninguna de estas medidas es una señal validada: entran al hard testing como cualquier estrategia.
"""
import hashlib
import json
import re
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# VADER es un léxico general: sin estas palabras puntuaba "Bitcoin plunges ... liquidations top 1 billion" como
# positivo. Escala de VADER (-4 a 4). Cambiar esta tabla es cambiar el modelo: sube la versión.
CRYPTO_LEXICON = {
    "bullish": 2.0, "bearish": -2.0, "rally": 1.8, "rallies": 1.8, "surge": 1.8, "surges": 1.8, "soar": 2.0,
    "soars": 2.0, "rebound": 1.2, "rebounds": 1.2, "breakout": 1.2, "inflows": 1.2, "adoption": 1.0,
    "plunge": -2.2, "plunges": -2.2, "tumble": -1.8, "tumbles": -1.8, "slump": -1.8, "slumps": -1.8,
    "selloff": -2.0, "sell-off": -2.0, "crash": -2.5, "crashes": -2.5, "liquidation": -1.5, "liquidations": -1.5,
    "liquidated": -1.5, "hack": -2.5, "hacks": -2.5, "hacked": -2.5, "exploit": -2.0, "exploited": -2.0,
    "drained": -2.0, "outflows": -1.2, "delist": -1.8, "delisting": -1.8, "depeg": -2.5, "insolvency": -2.5,
    "bankrupt": -2.5, "bankruptcy": -2.5,
    # Dirección del precio: los titulares la dicen con verbos que el léxico general no conoce.
    "down": -1.2, "fall": -1.4, "falls": -1.4, "drops": -1.2, "slide": -1.4, "slides": -1.4, "sink": -1.6,
    "sinks": -1.6, "climb": 1.4, "climbs": 1.4, "jump": 1.4, "jumps": 1.4, "rise": 1.2, "rises": 1.2,
}
MODEL_VERSION = "vader-3.3.2+crypto-1"
MAX_TITLE = 500

# Nombres en cualquier caja; tickers ambiguos ("sol" en español, "link" en inglés) solo en mayúsculas.
SYMBOL_PATTERNS = {
    "BTCUSDT": re.compile(r"\b(?:bitcoin|btc)\b", re.I),
    "ETHUSDT": re.compile(r"\b(?:ethereum|ether|eth)\b", re.I),
    "SOLUSDT": re.compile(r"\b(?:[Ss]olana|SOLANA|SOL)\b"),
    "LINKUSDT": re.compile(r"\b(?:[Cc]hainlink|CHAINLINK|LINK)\b"),
    "ONDOUSDT": re.compile(r"\bondo\b", re.I),
}
ATOM = "{http://www.w3.org/2005/Atom}"
AGENT_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

_analyzer = None


def score(text):
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
        _analyzer.lexicon.update(CRYPTO_LEXICON)
    return round(_analyzer.polarity_scores(text or "")["compound"], 4)


def tag_symbols(text):
    return sorted(symbol for symbol, pattern in SYMBOL_PATTERNS.items() if pattern.search(text or ""))


def _utc_iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _from_ms(ms):
    return _utc_iso(datetime.fromtimestamp(int(ms) // 1000, tz=timezone.utc))


def news_item(source, guid, title, url, published_at, author=None):
    title = " ".join((title or "").split())[:MAX_TITLE]
    digest = hashlib.sha256((guid or url).encode()).hexdigest()[:20]
    return {
        "item_key": f"{source}:{digest}",
        "source": source,
        "author": author,
        "title": title,
        "url": url,
        "published_at": published_at,
        "symbols": tag_symbols(title),
        "sentiment": score(title),
        "sentiment_model": MODEL_VERSION,
    }


def _parse_date(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = parsedate_to_datetime(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_rss(source, xml_text, since):
    """RSS 2.0 (medios) o Atom (Reddit). Descarta lo publicado antes de `since` y lo que no tiene fecha."""
    root = ET.fromstring(xml_text)
    items = []
    for node in root.iter("item"):
        items.append((node.findtext("guid"), node.findtext("title"), node.findtext("link"), node.findtext("pubDate")))
    for node in root.iter(f"{ATOM}entry"):
        link = node.find(f"{ATOM}link")
        items.append((node.findtext(f"{ATOM}id"), node.findtext(f"{ATOM}title"),
                       link.get("href") if link is not None else None,
                       node.findtext(f"{ATOM}published") or node.findtext(f"{ATOM}updated")))
    out = []
    for guid, title, url, date in items:
        published = _parse_date(date)
        url = (url or "").strip()
        # La base exige https: un solo enlace http haría fallar la inserción de toda la tanda.
        if not (title and url.startswith("https://")) or published is None or published < since:
            continue
        out.append(news_item(source, guid, title, url, _utc_iso(published)))
    return out


def parse_bluesky(payload, since):
    """Feed de autor de Bluesky. Los reposts se descartan: interesa lo que publica la cuenta, no lo que comparte."""
    out = []
    for entry in payload.get("feed", []):
        if "reason" in entry:
            continue
        post = entry.get("post", {})
        record = post.get("record", {})
        published = _parse_date(record.get("createdAt"))
        handle = post.get("author", {}).get("handle")
        uri = post.get("uri", "")
        if not (handle and uri and record.get("text")) or published is None or published < since:
            continue
        url = f"https://bsky.app/profile/{handle}/post/{uri.rsplit('/', 1)[-1]}"
        out.append(news_item("bluesky", uri, record["text"], url, _utc_iso(published), author=handle))
    return out


def _observation(source, metric, symbol, value, observed_at, label=None):
    float(value)  # un valor no numérico rompería el insert de todas las observaciones: que falle solo su fuente
    return {"source": source, "metric": metric, "symbol": symbol, "value": str(value), "label": label,
            "observed_at": observed_at}


def parse_fear_greed(payload):
    return [
        _observation("alternative_me", "fear_greed", None, row["value"],
                     _utc_iso(datetime.fromtimestamp(int(row["timestamp"]), tz=timezone.utc)),
                     label=row.get("value_classification"))
        for row in payload.get("data", [])
    ]


def parse_funding(payload):
    return [_observation("binance_futures", "funding_rate", row["symbol"], row["fundingRate"],
                         _from_ms(row["fundingTime"])) for row in payload]


def parse_long_short(payload):
    return [_observation("binance_futures", "long_short_account_ratio", row["symbol"], row["longShortRatio"],
                         _from_ms(row["timestamp"])) for row in payload]


def _dollar_quote(text):
    # Un literal con etiqueta aleatoria que no aparece en el texto no puede cerrarse desde dentro:
    # los titulares vienen de internet y no deben poder inyectar SQL.
    while True:
        tag = f"$j{secrets.token_hex(6)}$"
        if tag not in text:
            return f"{tag}{text}{tag}"


def to_sql(observations, news, agent_id):
    """Un único script para execute_sql; los duplicados (misma fuente y momento, mismo item_key) se ignoran."""
    if not AGENT_ID.match(agent_id):
        raise ValueError(f"agent_id no válido: {agent_id!r}")
    statements = []
    if observations:
        payload = _dollar_quote(json.dumps(observations, ensure_ascii=False))
        statements.append(
            "insert into public.sentiment_observations (source, metric, symbol, value, label, observed_at, "
            "recorded_by_agent_id)\n"
            f"select source, metric, symbol, value, label, observed_at, '{agent_id}'\n"
            f"from jsonb_to_recordset({payload}::jsonb) as x(source text, metric text, symbol text, value numeric, "
            "label text, observed_at timestamptz)\non conflict do nothing;"
        )
    if news:
        payload = _dollar_quote(json.dumps(news, ensure_ascii=False))
        statements.append(
            "insert into public.news_items (item_key, source, author, title, url, published_at, symbols, sentiment, "
            "sentiment_model, recorded_by_agent_id)\n"
            f"select item_key, source, author, title, url, published_at, symbols, sentiment, sentiment_model, "
            f"'{agent_id}'\n"
            f"from jsonb_to_recordset({payload}::jsonb) as x(item_key text, source text, author text, title text, "
            "url text, published_at timestamptz, symbols text[], sentiment numeric, sentiment_model text)\n"
            "on conflict do nothing;"
        )
    return "\n".join(statements)
