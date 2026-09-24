import json
import re
import unittest
from datetime import datetime, timedelta, timezone

from tools.ingest_sentiment import collect, parse_since, summarize
from ai_trading_lab.sentiment import (
    MODEL_VERSION, news_item, parse_bluesky, parse_fear_greed, parse_funding, parse_long_short, parse_rss, score,
    tag_symbols, to_sql,
)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>CoinDesk</title>
  <item>
    <title><![CDATA[Bitcoin Plunges Below $80K as Liquidations Top $1B]]></title>
    <link>https://www.coindesk.com/markets/2026/09/24/btc-plunges/</link>
    <guid isPermaLink="false">a1b2c3</guid>
    <pubDate>Thu, 24 Sep 2026 03:15:00 +0000</pubDate>
  </item>
  <item>
    <title>Old news</title>
    <link>https://www.coindesk.com/old/</link>
    <pubDate>Mon, 21 Sep 2026 10:00:00 -0400</pubDate>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_1abcde</id>
    <title>SEC approves spot Solana ETF</title>
    <link href="https://www.reddit.com/r/CryptoCurrency/comments/1abcde/sec_approves/"/>
    <updated>2026-09-24T04:10:00+00:00</updated>
    <published>2026-09-24T04:05:00+00:00</published>
  </entry>
</feed>"""

BLUESKY = {"feed": [
    {"post": {"uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz", "author": {"handle": "coindesk.com"},
              "record": {"text": "Ether ETF inflows hit a record as ETH surges", "createdAt": "2026-09-24T04:00:00.000Z"}}},
    {"post": {"uri": "at://did:plc:zzz/app.bsky.feed.post/3kother", "author": {"handle": "someone.else"},
              "record": {"text": "reposted content", "createdAt": "2026-09-24T04:01:00.000Z"}},
     "reason": {"$type": "app.bsky.feed.defs#reasonRepost"}},
]}

NOW = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)


class ScoreTest(unittest.TestCase):
    def test_crypto_words_have_the_right_sign(self):
        # VADER sin léxico cripto daba +0.20 a este titular: "plunges" y "liquidations" no existían.
        self.assertLess(score("Bitcoin plunges below 80K as liquidations top 1 billion"), -0.3)
        self.assertLess(score("Exchange hacked, 200M drained in exploit"), -0.5)
        self.assertGreater(score("Ether ETF inflows hit record as price surges"), 0.3)
        self.assertGreater(score("SEC approves spot Solana ETF"), 0.3)
        # Titular real del 2026-09-24 que el léxico general puntuaba +0.20.
        self.assertLess(score("Dogecoin down 8%, bitcoin under $84,000 as Treasury yields hit highest level since 2007"), 0)
        self.assertGreater(score("Solana climbs as SOL jumps 10%"), 0.3)

    def test_score_is_bounded(self):
        for text in ["", "crash crash crash hack scam", "rally surge soar bullish record"]:
            self.assertTrue(-1 <= score(text) <= 1)

    def test_model_version_names_the_lexicon(self):
        self.assertIn("vader-3.3.2", MODEL_VERSION)
        self.assertIn("crypto", MODEL_VERSION)


class TagSymbolsTest(unittest.TestCase):
    def test_names_and_tickers(self):
        self.assertEqual(tag_symbols("ETH and BTC diverge"), ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(tag_symbols("Solana rallies; Chainlink and Ondo follow"), ["LINKUSDT", "ONDOUSDT", "SOLUSDT"])
        self.assertEqual(tag_symbols("SOL and LINK lead"), ["LINKUSDT", "SOLUSDT"])

    def test_common_words_are_not_tickers(self):
        # "sol" (español) y "link" (inglés) son palabras normales; solo cuentan en mayúsculas como ticker.
        self.assertEqual(tag_symbols("el sol sale; link in bio"), [])
        self.assertEqual(tag_symbols("Ethena and Bitcoiners"), [])


class ParseTest(unittest.TestCase):
    def test_rss_item_fields_and_utc_dates(self):
        items = parse_rss("coindesk", RSS, since=SINCE)
        self.assertEqual(len(items), 1)  # la noticia vieja queda fuera por --since
        [item] = items
        self.assertEqual(item["source"], "coindesk")
        self.assertEqual(item["title"], "Bitcoin Plunges Below $80K as Liquidations Top $1B")
        self.assertEqual(item["url"], "https://www.coindesk.com/markets/2026/09/24/btc-plunges/")
        self.assertEqual(item["published_at"], "2026-09-24T03:15:00+00:00")
        self.assertEqual(item["symbols"], ["BTCUSDT"])
        self.assertLess(item["sentiment"], 0)
        self.assertEqual(item["sentiment_model"], MODEL_VERSION)

    def test_rss_offset_dates_are_converted_to_utc(self):
        [old] = [i for i in parse_rss("coindesk", RSS, since=datetime(2020, 1, 1, tzinfo=timezone.utc))
                 if i["title"] == "Old news"]
        self.assertEqual(old["published_at"], "2026-09-21T14:00:00+00:00")

    def test_item_key_is_stable_and_source_scoped(self):
        a = parse_rss("coindesk", RSS, since=SINCE)[0]["item_key"]
        b = parse_rss("coindesk", RSS, since=SINCE)[0]["item_key"]
        c = parse_rss("decrypt", RSS, since=SINCE)[0]["item_key"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith("coindesk:"))

    def test_atom_feed_from_reddit(self):
        [item] = parse_rss("reddit_cryptocurrency", ATOM, since=SINCE)
        self.assertEqual(item["url"], "https://www.reddit.com/r/CryptoCurrency/comments/1abcde/sec_approves/")
        self.assertEqual(item["published_at"], "2026-09-24T04:05:00+00:00")
        self.assertEqual(item["symbols"], ["SOLUSDT"])

    def test_bluesky_skips_reposts_and_builds_web_url(self):
        [item] = parse_bluesky(BLUESKY, since=SINCE)
        self.assertEqual(item["source"], "bluesky")
        self.assertEqual(item["author"], "coindesk.com")
        self.assertEqual(item["url"], "https://bsky.app/profile/coindesk.com/post/3kxyz")
        self.assertEqual(item["symbols"], ["ETHUSDT"])

    def test_non_https_links_are_dropped(self):
        # La base exige https: un solo enlace http haría fallar la inserción de toda la tanda.
        rss = RSS.replace("https://www.coindesk.com/markets", "http://www.coindesk.com/markets")
        self.assertEqual(parse_rss("coindesk", rss, since=SINCE), [])

    def test_non_numeric_values_are_rejected_before_sql(self):
        with self.assertRaises(ValueError):
            parse_funding([{"symbol": "BTCUSDT", "fundingTime": 1790208000002, "fundingRate": "n/a"}])

    def test_long_titles_are_truncated(self):
        item = news_item("bluesky", "k", "x" * 900, "https://x", "2026-09-24T04:00:00+00:00")
        self.assertLessEqual(len(item["title"]), 500)

    def test_fear_greed(self):
        payload = {"data": [{"value": "71", "value_classification": "Greed", "timestamp": "1790208000"}]}
        [obs] = parse_fear_greed(payload)
        self.assertEqual(obs, {"source": "alternative_me", "metric": "fear_greed", "symbol": None, "value": "71",
                               "label": "Greed", "observed_at": "2026-09-24T00:00:00+00:00"})

    def test_funding_keeps_exact_decimal(self):
        payload = [{"symbol": "BTCUSDT", "fundingTime": 1790208000002, "fundingRate": "0.00000132"}]
        [obs] = parse_funding(payload)
        self.assertEqual(obs["value"], "0.00000132")
        self.assertEqual(obs["metric"], "funding_rate")
        self.assertEqual(obs["symbol"], "BTCUSDT")
        self.assertEqual(obs["observed_at"], "2026-09-24T00:00:00+00:00")

    def test_long_short(self):
        payload = [{"symbol": "BTCUSDT", "longShortRatio": "1.1668", "timestamp": 1790222400000}]
        [obs] = parse_long_short(payload)
        self.assertEqual((obs["metric"], obs["value"]), ("long_short_account_ratio", "1.1668"))


class ToSqlTest(unittest.TestCase):
    def test_payload_round_trips_inside_dollar_quotes(self):
        hostile = "Robert'); drop table news_items; -- $s$ $sent$"
        news = [news_item("coindesk", "g1", hostile, "https://x", "2026-09-24T04:00:00+00:00")]
        sql = to_sql([], news, agent_id="claude")
        tag = re.search(r"(\$[a-z0-9_]+\$)\[", sql).group(1)
        self.assertNotIn(tag, json.dumps(news, ensure_ascii=False))
        literal = sql.split(tag)[1]
        self.assertEqual(json.loads(literal)[0]["title"], hostile)

    def test_inserts_ignore_duplicates(self):
        sql = to_sql([{"source": "alternative_me", "metric": "fear_greed", "symbol": None, "value": "71",
                       "label": "Greed", "observed_at": "2026-09-24T00:00:00+00:00"}], [], agent_id="claude")
        self.assertIn("insert into public.sentiment_observations", sql)
        self.assertIn("on conflict do nothing", sql)
        self.assertNotIn("news_items", sql)

    def test_rejects_unknown_agent_ids_in_sql(self):
        with self.assertRaises(ValueError):
            to_sql([], [], agent_id="claude'; drop")


class CollectTest(unittest.TestCase):
    def fake_fetch(self, broken=()):
        def fetch(url):
            for fragment in broken:
                if fragment in url:
                    raise TimeoutError(f"caída simulada: {fragment}")
            if "stablecoincharts" in url:
                return json.dumps([{"date": str(1790208000 - (40 - k) * 86400), "totalCirculatingUSD": {"peggedUSD": 300e9 + k * 1e9}}
                                   for k in range(41)])
            if "api.llama.fi/protocols" in url:
                return json.dumps([{"category": "RWA", "tvl": 4.7e9}, {"category": "Dexs", "tvl": 1e9}])
            if "alternative.me" in url:
                return json.dumps({"data": [{"value": "71", "value_classification": "Greed", "timestamp": "1790208000"}]})
            if "fundingRate" in url:
                sym = re.search(r"symbol=(\w+)", url).group(1)
                return json.dumps([{"symbol": sym, "fundingTime": 1790208000002, "fundingRate": "0.0001"}])
            if "LongShort" in url:
                sym = re.search(r"symbol=(\w+)", url).group(1)
                return json.dumps([{"symbol": sym, "longShortRatio": "1.2", "timestamp": 1790222400000}])
            if "bsky" in url:
                return json.dumps(BLUESKY)
            if "reddit" in url:
                return ATOM
            return RSS
        return fetch

    def test_collects_every_source(self):
        result = collect(SINCE, fetch=self.fake_fetch())
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["observations"]), 1 + 2 + 1 + 5 + 5)
        sources = {i["source"] for i in result["news"]}
        self.assertEqual(sources, {"coindesk", "cointelegraph", "decrypt", "reddit_cryptocurrency", "bluesky",
                                   "oilprice", "cnbc_energy", "investing_commodities"})

    def test_duplicate_items_are_collapsed(self):
        # Las tres cuentas de Bluesky devuelven el mismo post en la prueba: debe quedar uno.
        result = collect(SINCE, fetch=self.fake_fetch())
        self.assertEqual(sum(1 for i in result["news"] if i["source"] == "bluesky"), 1)

    def test_a_broken_source_does_not_stop_the_rest(self):
        result = collect(SINCE, fetch=self.fake_fetch(broken=("reddit", "alternative.me")))
        self.assertEqual({e["source"] for e in result["errors"]}, {"reddit_cryptocurrency", "alternative_me"})
        self.assertEqual(len(result["observations"]), 13)
        self.assertIn("coindesk", {i["source"] for i in result["news"]})

    def test_summary_includes_stablecoin_growth_like_the_strategy(self):
        # Último día k=40; con un día de retraso se compara k=39 con k=9: (339/309) - 1.
        summary = summarize(collect(SINCE, fetch=self.fake_fetch()))
        self.assertAlmostEqual(summary["stablecoin_growth_30d"], round(339 / 309 - 1, 5))

    def test_summary_lists_negative_headlines(self):
        summary = summarize(collect(SINCE, fetch=self.fake_fetch()))
        self.assertEqual(summary["observations"]["fear_greed:MERCADO"], "71")
        self.assertTrue(all(i["sentiment"] < 0 for i in summary["most_negative"]))
        self.assertIn("Plunges", summary["most_negative"][0]["title"])

    def test_since_is_capped_at_48_hours(self):
        self.assertEqual(parse_since("2020-01-01T00:00:00Z", NOW), NOW - timedelta(hours=48))
        self.assertEqual(parse_since(None, NOW), NOW - timedelta(hours=6))
        self.assertEqual(parse_since("2026-09-24T04:00:00Z", NOW), datetime(2026, 9, 24, 4, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
