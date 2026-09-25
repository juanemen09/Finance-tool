"""Tesis de infraestructura de IA: 13F, capex, citas, conversiones físicas y oferta (Corea, Taiwán).
Todo sin red: los formatos imitan los reales (13F de Situational Awareness, XBRL de la SEC, Comtrade, ODS de Taiwán)."""
import io
import json
import unittest
import zipfile

from ai_trading_lab import research as r

INFO_TABLE = """<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>MICRON TECHNOLOGY INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip>595112103</cusip><value>600</value>
    <shrsOrPrnAmt><sshPrnamt>6</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
  <infoTable><nameOfIssuer>BLOOM ENERGY CORP</nameOfIssuer><titleOfClass>COM CL A</titleOfClass>
    <cusip>093712107</cusip><value>300</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
  <infoTable><nameOfIssuer>BLOOM ENERGY CORP</nameOfIssuer><titleOfClass>COM CL A</titleOfClass>
    <cusip>093712107</cusip><value>100</value>
    <shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <putCall>Call</putCall></infoTable>
  <infoTable><nameOfIssuer>INFOSYS LTD</nameOfIssuer><titleOfClass>SPONSORED ADR</titleOfClass>
    <cusip>456788108</cusip><value>50</value>
    <shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <putCall>Put</putCall></infoTable>
  <infoTable><nameOfIssuer>BLOOM ENERGY CORP</nameOfIssuer><titleOfClass>COM CL A</titleOfClass>
    <cusip>093712107</cusip><value>100</value>
    <shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
</informationTable>"""


def fact(start, end, val, filed="2026-01-01", form="10-Q", accn="a"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "accn": accn}


class ThirteenF(unittest.TestCase):
    def test_filings_keep_only_13f_newest_report_first(self):
        subs = {"filings": {"recent": {
            "form": ["4", "13F-HR", "13F-HR/A", "13F-HR"],
            "accessionNumber": ["x", "0001-26-000418", "0001-26-000300", "0001-26-000200"],
            "filingDate": ["2026-09-17", "2026-08-14", "2026-06-01", "2026-05-15"],
            "reportDate": ["2026-09-15", "2026-06-30", "2026-03-31", "2026-03-31"],
            "primaryDocument": ["f4.xml", "p.xml", "p.xml", "p.xml"]}}}
        latest, previous = r.pick_13f(r.parse_13f_filings(subs))
        self.assertEqual(latest["accession"], "0001-26-000418")
        self.assertEqual(previous["accession"], "0001-26-000200", "la enmienda no sustituye al original anterior")

    def test_table_and_long_book_drop_options_and_merge_lines(self):
        holdings = r.parse_13f_table(INFO_TABLE, filing_date="2026-08-14")
        self.assertEqual(len(holdings), 5)
        self.assertEqual({h["put_call"] for h in holdings}, {None, "Call", "Put"})
        book = r.long_book(holdings)
        self.assertEqual([b["cusip"] for b in book], ["595112103", "093712107"])
        bloom = book[1]
        self.assertEqual((bloom["shares"], bloom["value_usd"]), (15, 400), "dos líneas de la misma acción se suman")
        self.assertAlmostEqual(book[0]["weight"], 0.6)
        self.assertAlmostEqual(sum(b["weight"] for b in book), 1.0)
        self.assertAlmostEqual(bloom["implied_price"], 400 / 15)

    def test_values_before_2023_were_in_thousands(self):
        old = r.parse_13f_table(INFO_TABLE, filing_date="2022-11-14")
        self.assertEqual(old[0]["value_usd"], 600_000)

    def test_changes_between_quarters(self):
        prev = [{"cusip": "A", "issuer": "a", "shares": 10}, {"cusip": "B", "issuer": "b", "shares": 10},
                {"cusip": "C", "issuer": "c", "shares": 10}]
        cur = [{"cusip": "A", "issuer": "a", "shares": 15}, {"cusip": "B", "issuer": "b", "shares": 10},
               {"cusip": "D", "issuer": "d", "shares": 3}]
        changes = {c["cusip"]: c["change"] for c in r.book_changes(prev, cur)}
        self.assertEqual(changes, {"A": "ADD", "B": "SAME", "C": "EXIT", "D": "NEW"})

    def test_order_list_is_hypothetical_and_proportional(self):
        book = [{"cusip": "A", "ticker": "MU", "issuer": "m", "weight": 0.75, "implied_price": 100.0},
                {"cusip": "B", "ticker": None, "issuer": "b", "weight": 0.25, "implied_price": 7.0}]
        orders = r.size_orders(book, notional=1000)
        self.assertEqual([o["amount_usd"] for o in orders], [750.0, 250.0])
        self.assertEqual(orders[0]["approx_shares"], 7.5)
        self.assertEqual(orders[1]["approx_shares"], 35.7142, "se redondea hacia abajo, nunca por encima del monto")
        with self.assertRaises(ValueError):
            r.size_orders(book, notional=0)

    def test_figi_prefers_us_listing(self):
        resp = [{"data": [{"ticker": "MU1", "exchCode": "GR"}, {"ticker": "MU", "exchCode": "US"}]},
                {"warning": "No identifier found."}, {"data": [{"ticker": "1B2", "exchCode": "GF"}]}]
        self.assertEqual(r.parse_figi(["595112103", "X", "Y"], resp), {"595112103": "MU"})


class Capex(unittest.TestCase):
    def test_quarters_from_year_to_date_cash_flow(self):
        units = [
            fact("2025-01-01", "2025-03-31", 10), fact("2025-01-01", "2025-06-30", 25),
            fact("2025-01-01", "2025-09-30", 45), fact("2025-01-01", "2025-12-31", 70, form="10-K"),
            fact("2026-01-01", "2026-03-31", 30),
            fact("2026-01-01", "2026-06-30", 60, filed="2026-07-01"),
            fact("2026-01-01", "2026-06-30", 999, filed="2025-01-01"),  # versión vieja: gana la última presentada
            fact("2024-01-01", "2024-12-31", 50, form="8-K"),           # otros formularios no cuentan
        ]
        q = r.quarterly_from_ytd(units)
        self.assertEqual([(x["end"], x["value"]) for x in q],
                         [("2025-03-31", 10), ("2025-06-30", 15), ("2025-09-30", 20), ("2025-12-31", 25),
                          ("2026-03-31", 30), ("2026-06-30", 30)])
        self.assertTrue(q[1]["derived"])
        self.assertFalse(q[0]["derived"])

    def test_summary_growth_and_acceleration(self):
        q = [{"end": e, "value": v} for e, v in [
            ("2025-03-31", 10), ("2025-06-30", 10), ("2025-09-30", 10), ("2025-12-31", 10),
            ("2026-03-31", 12), ("2026-06-30", 15)]]
        s = r.capex_summary(q)
        self.assertEqual(s["latest_usd"], 15)
        self.assertAlmostEqual(s["qoq_pct"], 25.0)
        self.assertAlmostEqual(s["yoy_pct"], 50.0)
        self.assertAlmostEqual(s["acceleration_pp"], 30.0, msg="interanual 50 % frente a 20 % el trimestre anterior")
        self.assertEqual(s["ttm_usd"], 47)

    def test_summary_without_history_does_not_invent(self):
        s = r.capex_summary([{"end": "2026-06-30", "value": 5}])
        self.assertIsNone(s["yoy_pct"])
        self.assertIsNone(s["ttm_usd"])

    def test_instant_series_for_backlog(self):
        units = [{"end": "2026-03-31", "val": 1, "filed": "2026-04-01", "form": "10-Q", "accn": "a"},
                 {"end": "2026-06-30", "val": 2, "filed": "2026-07-01", "form": "10-Q", "accn": "b"},
                 {"end": "2026-06-30", "val": 3, "filed": "2026-08-01", "form": "10-Q/A", "accn": "c"}]
        self.assertEqual([(x["end"], x["value"]) for x in r.instant_series(units)],
                         [("2026-03-31", 1), ("2026-06-30", 3)])


class Quotes(unittest.TestCase):
    HTML = """<html><head><style>p{x}</style><script>var capital expenditures increased;</script></head><body>
    <div style="display:none"><ix:header>Capital expenditures increased hidden fact that must not appear.</ix:header></div>
    <p>Revenue grew 20% in the quarter.</p>
    <p>Cash used for capital expenditures increased $8.4 billion, primarily driven by investments in data centers
    and servers to support AI demand.</p><p>Capital expenditures increased again, primarily driven by
    investments in data centers and servers to support AI demand.</p>
    <p>We describe property and equipment in Note 5.</p>
    </body></html>"""

    def test_only_causal_capex_sentences_verbatim(self):
        quotes = r.extract_quotes(self.HTML, r.CAPEX_QUOTE)
        self.assertEqual(len(quotes), 2)
        self.assertTrue(quotes[0].startswith("Cash used for capital expenditures increased $8.4 billion"))
        self.assertTrue(all("hidden" not in q and "var " not in q for q in quotes))
        self.assertNotIn("Note 5", " ".join(quotes), "mencionar el activo fijo sin causa no explica el cambio")

    def test_page_break_is_joined_and_fragments_dropped(self):
        html = ("<div>As of June 30, 2026, backlog increased $26.0 billion (17%) from December 31, 2025, primarily at "
                "Gas Power due to</div><div>higher Heavy-Duty gas turbine orders and slot reservations.</div>"
                "<td>Gas Power backlog increased due to orders</td>")
        quotes = r.extract_quotes(html, r.TURBINE_QUOTE)
        self.assertEqual(quotes, ["As of June 30, 2026, backlog increased $26.0 billion (17%) from December 31, 2025, "
                                  "primarily at Gas Power due to higher Heavy-Duty gas turbine orders and slot "
                                  "reservations."])

    def test_max_quotes(self):
        self.assertEqual(len(r.extract_quotes(self.HTML, r.CAPEX_QUOTE, max_quotes=1)), 1)


class Physical(unittest.TestCase):
    A = {
        "datacenter_share": {"low": 0.8, "mid": 0.9, "high": 1.0},
        "cost_per_mw_usd": {"low": 35e6, "mid": 50e6, "high": 60e6},
        "hbm_gb_per_it_mw": {"low": 100_000, "mid": 125_000, "high": 150_000},
        "pue": {"low": 1.1, "mid": 1.2, "high": 1.4},
        "sqft_per_mw": {"low": 1500, "mid": 3000, "high": 5000},
        "turbine_mw": {"heavy_duty": 430, "aeroderivative": 50},
    }

    def test_ranges_are_ordered_and_show_working(self):
        p = r.to_physical(100e9, self.A)
        mw = p["megawatts"]
        self.assertAlmostEqual(mw["mid"], 100e9 * 0.9 / 50e6)
        self.assertAlmostEqual(mw["low"], 100e9 * 0.8 / 60e6)
        self.assertAlmostEqual(mw["high"], 100e9 * 1.0 / 35e6)
        for key in ("megawatts", "hbm_gb", "square_feet", "heavy_duty_turbines", "aeroderivative_turbines"):
            self.assertLessEqual(p[key]["low"], p[key]["mid"])
            self.assertLessEqual(p[key]["mid"], p[key]["high"])
        self.assertAlmostEqual(p["hbm_gb"]["mid"], mw["mid"] / 1.2 * 125_000)
        self.assertAlmostEqual(p["heavy_duty_turbines"]["mid"], mw["mid"] / 430)
        self.assertIn("50", p["working"]["megawatts"])


def ods(rows):
    t = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    x = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    cells = lambda row: "".join(f'<table:table-cell><text:p>{c}</text:p></table:table-cell>' for c in row)
    body = "".join(f"<table:table-row>{cells(row)}</table:table-row>" for row in rows)
    content = (f'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               f'xmlns:table="{t}" xmlns:text="{x}"><office:body><office:spreadsheet>'
               f'<table:table table:name="表1"></table:table><table:table table:name="表2p1">{body}</table:table>'
               f'</office:spreadsheet></office:body></office:document-content>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", content)
    return buf.getvalue()


class Supply(unittest.TestCase):
    def test_taiwan_orders_by_month_with_roc_years(self):
        data = ods([
            ["年 月", "", "總 計", "", "資訊通信", "", "電子產品", ""],
            ["114年", "", "7437.29", "25.9", "2334.2", "35.6", "2916.2", "37.8"],
            ["114年", "12月", "761.97", "43.79", "286.83", "88.07", "278.66", "39.91"],
            ["115年1-8月", "", "7049.8", "55.0", "2476.1", "87.6", "2963.1", "65.1"],
            ["115年", "1月", "769.07", "60.10", "251.45", "102.04", "325.91", "78.56"],
            ["", "8月", "1029.55", "71.35", "342.10", "100.51", "457.54", "83.90"],
            ["較上月增減", "", "50.16", "5.12", "9.41", "2.83", "44.36", "10.73"],
        ])
        rows = r.parse_taiwan_orders_ods(data)
        self.assertEqual([x["period"] for x in rows], ["2025-12", "2026-01", "2026-08"])
        aug = rows[-1]
        self.assertAlmostEqual(aug["total_usd"] / 1e8, 1029.55)
        self.assertAlmostEqual(aug["ict_usd"] / 1e8, 342.10)
        self.assertAlmostEqual(aug["electronics_yoy_pct"], 83.90)

    def test_comtrade_world_exports_only(self):
        payload = {"count": 2, "data": [
            {"period": "202506", "flowCode": "X", "partnerCode": 0, "cmdCode": "854232", "primaryValue": 9.5e9,
             "netWgt": 1200.0},
            {"period": "202506", "flowCode": "X", "partnerCode": 156, "cmdCode": "854232", "primaryValue": 1e9}]}
        self.assertEqual(r.parse_comtrade(payload),
                         [{"period": "2025-06", "value_usd": 9.5e9, "net_kg": 1200.0}])

    def test_yoy_growth_from_monthly_series(self):
        series = [{"period": "2025-06", "value_usd": 10.0}, {"period": "2026-06", "value_usd": 15.0},
                  {"period": "2026-07", "value_usd": 9.0}]
        self.assertEqual(r.yoy_by_period(series, "value_usd"), {"2026-06": 50.0})


class Reports(unittest.TestCase):
    def test_report_key_changes_only_with_data(self):
        a = r.report_row("AI_DEMAND", "2026-09-25", "t", "b", {"x": 1})
        b = r.report_row("AI_DEMAND", "2026-09-26", "t", "otro texto", {"x": 1})
        c = r.report_row("AI_DEMAND", "2026-09-26", "t", "b", {"x": 2})
        self.assertEqual(a["report_key"], b["report_key"], "sin datos nuevos no hay informe nuevo")
        self.assertNotEqual(a["report_key"], c["report_key"])
        d = r.report_row("AI_DEMAND", "2026-09-27", "t", "b", {"x": 1, "comparison": {"x": {"change": 0}}})
        self.assertEqual(a["report_key"], d["report_key"], "comparar de nuevo con el mismo informe no es un dato nuevo")
        json.dumps(a)

    def test_compare_headlines(self):
        prev = {"headline": {"capex_ttm_usd": 100.0, "memory_yoy_pct": 10.0}}
        cur = {"headline": {"capex_ttm_usd": 120.0, "memory_yoy_pct": 5.0, "new": 1.0}}
        d = r.compare_headlines(prev, cur)
        self.assertEqual(d["capex_ttm_usd"], {"previous": 100.0, "current": 120.0, "change": 20.0})
        self.assertEqual(d["new"], {"previous": None, "current": 1.0, "change": None})

    def test_sql_is_injection_safe(self):
        facts = [r.fact_row("ai_demand", "filing_quote", "MSFT", "2026-06-30", None, "text",
                            {"text": "$j'); drop table x; --"}, "https://www.sec.gov/x", key="q:1")]
        sql = r.to_sql_statements(facts, [], "claude")
        self.assertEqual(len(sql), 1)
        self.assertIn("on conflict do nothing", sql[0])
        with self.assertRaises(ValueError):
            r.to_sql_statements(facts, [], "claude'; --")
        with self.assertRaises(ValueError):
            r.fact_row("ai_demand", "m", "E", "2026-06-30", 1, "USD", {}, "http://insecure", key="k")


if __name__ == "__main__":
    unittest.main()
