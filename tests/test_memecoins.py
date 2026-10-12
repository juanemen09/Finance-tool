import unittest
from datetime import datetime, timedelta, timezone

from ai_trading_lab import memecoins as mc

NOW = datetime(2026, 10, 12, 19, tzinfo=timezone.utc)
MINT = "5THtNEGTF1y67eRWvcgz3MomDZePCVx1xdskHHeCpump"
POOL = "HJZMbpTZGuq5Nkss7CrDV4ooxfYKLv7p5aWiqYSBDdq2"


def clean(**kw):
    base = {"mint_revoked": True, "freeze_revoked": True, "lp_locked_pct": 100, "top10_pct": 20, "insider_supply_pct": 0,
            "insider_networks": 0, "insider_wallets": 0, "creator_pct": 0, "risks": [], "liquidity_usd": 60_000,
            "market_cap_usd": 400_000, "volume_h1": 1_000, "pair_created_at": NOW - timedelta(days=30)}
    return {**base, **kw}


class DiscoveryTest(unittest.TestCase):
    def test_sources_keep_only_solana_mints(self):
        items = [{"chainId": "solana", "tokenAddress": MINT}, {"chainId": "bsc", "tokenAddress": "0xabc"},
                 {"chainId": "solana", "tokenAddress": "So11111111111111111111111111111111111111112"},  # SOL no es memecoin
                 {"chainId": "solana", "tokenAddress": "no-es-direccion"}]
        self.assertEqual(mc.mints_from_dexscreener(items), [(MINT, "dexscreener_profile")])
        gecko = {"data": [{"relationships": {"base_token": {"data": {"id": f"solana_{MINT}"}}}}]}
        self.assertEqual(mc.mints_from_gecko(gecko, "gecko_trending"), [(MINT, "gecko_trending")])

    def test_reddit_mentions_by_address_and_ticker(self):
        entries = [(f"mira {MINT} y $SATUR va a volar", NOW - timedelta(hours=1)),
                   ("$satur otra vez", NOW - timedelta(hours=2)), ("$SATUR viejo", NOW - timedelta(hours=9))]
        addresses, tickers = mc.reddit_mentions(entries)
        self.assertIn(MINT, addresses)
        self.assertEqual(mc.count_mentions(MINT, "SATUR", addresses, tickers, NOW), 3)  # 1 dirección + 2 tickers recientes
        self.assertEqual(mc.count_mentions(MINT, "AI", {}, {"AI": [NOW]}, NOW), 0)  # tickers de 2 letras: demasiado ambiguos


class SafetyTest(unittest.TestCase):
    def test_pool_and_known_accounts_do_not_count_as_holders(self):
        report = {"mintAuthority": None, "freezeAuthority": None, "totalHolders": 8874, "score_normalised": 1,
                  "token": {"supply": 1_000_000}, "creatorBalance": 0,
                  "knownAccounts": {"CREATOR111111111111111111111111111": {"type": "CREATOR"}},
                  "markets": [{"pubkey": "MKT", "lp": {"lpLockedPct": 100}}],
                  "topHolders": [{"owner": POOL, "pct": 8.3}, {"owner": "A", "pct": 4.2}, {"owner": "B", "pct": 4.2, "insider": True}],
                  "insiderNetworks": [{"currentHolding": 300_000}, {"currentHolding": 70_000}], "graphInsidersDetected": 41}
        s = mc.safety_from_rugcheck(report, POOL)
        self.assertEqual(s["top10_pct"], 8.4)
        self.assertTrue(s["mint_revoked"] and s["freeze_revoked"])
        self.assertEqual((s["insider_networks"], s["insider_wallets"], s["insider_supply_pct"]), (2, 41, 37.0))
        self.assertEqual(s["insider_holder_pct"], 4.2)


class ScoreTest(unittest.TestCase):
    def test_clean_token_scores_zero_risk(self):
        self.assertEqual(mc.risk_score(clean(), NOW), (0.0, []))

    def test_each_trap_adds_risk(self):
        score, flags = mc.risk_score(clean(mint_revoked=False, freeze_revoked=False), NOW)
        self.assertEqual(score, 70)
        self.assertIn("el creador puede imprimir más", flags)
        score, flags = mc.risk_score(clean(insider_supply_pct=37, insider_networks=5, insider_wallets=53), NOW)
        self.assertEqual(score, 30)
        self.assertIn("insiders controlan 37 % (5 redes, 53 billeteras)", flags)

    def test_bot_volume_and_new_pairs_are_risky(self):
        score, flags = mc.risk_score(clean(volume_h1=2_000_000, pair_created_at=NOW - timedelta(minutes=20)), NOW)
        self.assertEqual(score, 35)
        self.assertTrue(any("bots" in f for f in flags))

    def test_implausible_insider_share_is_flagged_not_trusted(self):
        score, flags = mc.risk_score(clean(insider_supply_pct=100, insider_wallets=6437), NOW)
        self.assertEqual(score, 15)
        self.assertIn("dudoso", flags[0])

    def test_attention_rewards_volume_buyers_and_mentions(self):
        quiet, _ = mc.attention_score(clean(volume_h1=0.04, buys_h1=1, sells_h1=0))
        hot, flags = mc.attention_score(clean(volume_h1=40_000, buys_h1=240, sells_h1=60, price_change_h1=40,
                                              mentions_6h=5, volume_h24=400_000))
        self.assertLess(quiet, 2)
        self.assertGreater(hot, 85)
        self.assertIn("5 mención(es) en Reddit en 6 h", flags)


class AlertTest(unittest.TestCase):
    def snap(self, **kw):
        return {**clean(), "price_usd": 0.001, "attention_score": 70, "risk_score": 10, **kw}

    def test_alert_needs_attention_safety_liquidity_and_age(self):
        self.assertIsNotNone(mc.should_alert(self.snap(), None, NOW))
        self.assertIsNone(mc.should_alert(self.snap(attention_score=40), None, NOW))
        self.assertIsNone(mc.should_alert(self.snap(risk_score=45), None, NOW))
        self.assertIsNone(mc.should_alert(self.snap(liquidity_usd=5_000), None, NOW))
        self.assertIsNone(mc.should_alert(self.snap(pair_created_at=NOW - timedelta(minutes=30)), None, NOW))
        self.assertIsNone(mc.should_alert(self.snap(), NOW - timedelta(hours=3), NOW))  # ya avisado hoy
        self.assertIsNone(mc.should_alert(self.snap(volume_h1=2_000_000), None, NOW))  # volumen de bots

    def test_forward_test_horizons_and_dead_tokens(self):
        alerts = [{"id": 1, "alerted_at": NOW - timedelta(hours=25)}]
        self.assertEqual([h for _, h in mc.outcomes_due(alerts, {(1, 1)}, NOW)], [24])
        self.assertEqual(mc.outcome_return(0.001, None)["return_pct"], -100.0)
        alive = mc.outcome_return(0.001, {"priceUsd": "0.0015", "liquidity": {"usd": 30_000}})
        self.assertAlmostEqual(alive["return_pct"], 50.0)

    def test_negative_price_changes_survive(self):
        m = mc.market_from_pair({"chainId": "solana", "pairAddress": POOL, "priceChange": {"h1": -12.5}, "baseToken": {}})
        self.assertEqual(m["price_change_h1"], -12.5)


if __name__ == "__main__":
    unittest.main()
