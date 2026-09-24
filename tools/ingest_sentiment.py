"""Recolector de sentimiento: Fear & Greed, funding y largo/corto de Binance, titulares y Reddit/Bluesky.

Todas las fuentes son gratuitas y públicas. Una fuente caída no detiene a las demás: queda en `errors`.
Con --sql imprime un único script para execute_sql (duplicados ignorados) y deja el resumen en stderr.

Uso:  python -m tools.ingest_sentiment [--since 2026-09-24T03:00:00Z] [--sql] [--agent claude]
      python -m tools.ingest_sentiment --since ... --out data/raw/sentiment.sql --summary data/raw/sentiment_summary.json
"""
import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ai_trading_lab.sentiment import (
    parse_bluesky, parse_fear_greed, parse_funding, parse_long_short, parse_rss, to_sql,
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT"]
RSS_FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
    "reddit_cryptocurrency": "https://www.reddit.com/r/CryptoCurrency/new/.rss?limit=50",
}
# Cuentas verificadas el 2026-09-24: las de Cointelegraph, The Block y Blockworks no existen en Bluesky, y la de
# CoinDesk no publica desde febrero de 2025 (su RSS sí está al día).
BLUESKY_ACCOUNTS = ["decrypt.co", "watcher.guru"]
BLUESKY_FEED = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
FEAR_GREED = "https://api.alternative.me/fng/?limit=2&format=json"
FUTURES = "https://fapi.binance.com"
USER_AGENT = "ai-trading-lab/1.0 (personal research; hourly)"
MAX_LOOKBACK = timedelta(hours=48)


def fetch_text(url, attempts=3):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body.decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as exc:
            # 4xx es una respuesta definitiva (bloqueo, cuenta inexistente): reintentar no la cambia.
            if isinstance(exc, urllib.error.HTTPError) and exc.code < 500 or attempt == attempts:
                raise
            time.sleep(2 * attempt)


def collect(since, fetch=fetch_text):
    observations, news, errors = [], [], []

    def attempt(name, fn):
        try:
            return fn()
        except Exception as exc:  # una fuente rota no debe tumbar el resto del ciclo
            errors.append({"source": name, "error": f"{type(exc).__name__}: {exc}"[:300]})
            return []

    observations += attempt("alternative_me", lambda: parse_fear_greed(json.loads(fetch(FEAR_GREED))))
    for symbol in SYMBOLS:
        q = urllib.parse.urlencode({"symbol": symbol, "limit": 1})
        observations += attempt(f"funding:{symbol}", lambda: parse_funding(
            json.loads(fetch(f"{FUTURES}/fapi/v1/fundingRate?{q}"))))
        q2 = urllib.parse.urlencode({"symbol": symbol, "period": "1h", "limit": 1})
        observations += attempt(f"long_short:{symbol}", lambda: parse_long_short(
            json.loads(fetch(f"{FUTURES}/futures/data/globalLongShortAccountRatio?{q2}"))))
    for source, url in RSS_FEEDS.items():
        news += attempt(source, lambda: parse_rss(source, fetch(url), since=since))
    for handle in BLUESKY_ACCOUNTS:
        q = urllib.parse.urlencode({"actor": handle, "limit": 30})
        news += attempt(f"bluesky:{handle}", lambda: parse_bluesky(json.loads(fetch(f"{BLUESKY_FEED}?{q}")),
                                                                  since=since))
    unique = {item["item_key"]: item for item in news}
    news = sorted(unique.values(), key=lambda i: i["published_at"])
    return {"observations": observations, "news": news, "errors": errors}


def summarize(result):
    per_source = {}
    for item in result["news"]:
        per_source[item["source"]] = per_source.get(item["source"], 0) + 1
    by_tone = sorted(result["news"], key=lambda i: i["sentiment"])
    brief = lambda i: {"sentiment": i["sentiment"], "symbols": i["symbols"], "source": i["source"],
                       "title": i["title"][:160], "published_at": i["published_at"]}
    return {
        "observations": {f"{o['metric']}:{o['symbol'] or 'MERCADO'}": o["value"] for o in result["observations"]},
        "news_per_source": per_source,
        "most_negative": [brief(i) for i in by_tone[:5] if i["sentiment"] < 0],
        "most_positive": [brief(i) for i in reversed(by_tone[-3:]) if i["sentiment"] > 0],
        "errors": result["errors"],
    }


def parse_since(text, now):
    since = datetime.fromisoformat(text.replace("Z", "+00:00")) if text else now - timedelta(hours=6)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return max(since, now - MAX_LOOKBACK)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="solo titulares publicados después (ISO UTC); por defecto hace 6h, máx. 48h")
    parser.add_argument("--sql", action="store_true", help="imprime el script de inserción; el resumen va a stderr")
    parser.add_argument("--agent", default="claude")
    # Escribir los archivos desde Python evita la redirección de la consola: en PowerShell 5.1, `>` guarda UTF-16.
    parser.add_argument("--out", help="archivo donde escribir el script SQL (UTF-8)")
    parser.add_argument("--summary", help="archivo donde escribir el resumen JSON (UTF-8)")
    args = parser.parse_args()
    # En Windows la consola usa cp1252: las comillas tipográficas de los titulares llegaban como '?'.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    since = parse_since(args.since, datetime.now(timezone.utc))
    result = collect(since)
    summary = summarize(result)
    if args.out or args.summary:
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(to_sql(result["observations"], result["news"], agent_id=args.agent) + "\n")
        if args.summary:
            with open(args.summary, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=1)
        print(json.dumps({"news": len(result["news"]), "observations": len(result["observations"]),
                          "errors": len(result["errors"])}))
    elif args.sql:
        sys.stdout.write(to_sql(result["observations"], result["news"], agent_id=args.agent) + "\n")
        sys.stderr.write(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    else:
        print(json.dumps({**result, "summary": summary}, ensure_ascii=False, indent=1))
    # Si no llegó nada de ninguna fuente, el ciclo debe enterarse (fallo de red, no "mercado tranquilo").
    return 1 if not result["observations"] and not result["news"] else 0


if __name__ == "__main__":
    sys.exit(main())
