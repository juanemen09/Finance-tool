"""Tesis de infraestructura de IA: libro 13F, demanda (capex) y oferta física. Investigación, nunca órdenes.

Fuentes gratuitas y oficiales:
- SEC EDGAR: el 13F-HR de Situational Awareness LP, el XBRL de los 10-Q/10-K y sus textos. La SEC exige un
  contacto en el User-Agent: se toma de SEC_USER_AGENT en el .env.
- OpenFIGI: CUSIP → ticker.
- Comtrade de la ONU: exportaciones de memorias de Corea (SA 854232).
- Ministerio de Economía de Taiwán: boletín mensual de pedidos de exportación.

Uso:  python -m tools.ai_research all --insert            (escribe con lab_ingest; compara con dashboard_reader)
      python -m tools.ai_research book --notional 1000    (lista de órdenes HIPOTÉTICA; no se envía nada)
      python -m tools.ai_research demand|supply --out data/raw/ai_research.json
"""
import argparse
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from ai_trading_lab import research as r
from dashboard.config import load_env

SEC_DATA = "https://data.sec.gov"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
FUND = ("Situational Awareness LP", "0002045724")
BUYERS = {"MSFT": "0000789019", "AMZN": "0001018724", "GOOGL": "0001652044", "META": "0001326801",
          "ORCL": "0001341439"}
NVDA = ("NVDA", "0001045810")  # proveedor, no comprador: va aparte para no inflar la demanda
GEV = ("GEV", "0001996810")    # GE Vernova: turbinas de gas
MU = ("MU", "0000723125")      # Micron: memoria (HBM)
CAPEX_CONCEPTS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                  "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets")
REVENUE_CONCEPTS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues")
BACKLOG_CONCEPT = "RevenueRemainingPerformanceObligation"
OPENFIGI = "https://api.openfigi.com/v3/mapping"
COMTRADE = ("https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=410&period={period}"
            "&cmdCode=854232&flowCode=X&partnerCode=0")
TAIWAN = "https://www.moea.gov.tw/Mns/dos/bulletin/Bulletin.aspx?kind=5&html=1&menu_id=6724"
TAIWAN_FILE = "https://www.moea.gov.tw/Mns/DOS/bulletin/wHandBulletin_File.ashx?file_id={file_id}"
ASSUMPTIONS = Path(__file__).resolve().parent.parent / "config" / "ai_infra_assumptions.json"
USER_AGENT = "ai-trading-lab/1.0 (personal research; monthly)"
KOREA_MONTHS = 30  # Comtrade publica a Corea con ~9 meses de retraso: hace falta el año anterior para comparar


class Http:
    """Descargas con pausa por servidor (la SEC pide ≤10 por segundo) y reintentos en 429 y 5xx."""

    def __init__(self, sec_user_agent=None, sleep=time.sleep):
        self.sec_ua, self.sleep, self.last = sec_user_agent, sleep, {}

    def get(self, url, data=None, headers=None, attempts=4):
        host = urllib.parse.urlparse(url).hostname
        sec = host.endswith("sec.gov")
        if sec and not self.sec_ua:
            raise RuntimeError("Falta SEC_USER_AGENT en .env (la SEC exige nombre y correo de contacto)")
        pause = {"comtradeapi.un.org": 3.0, "api.openfigi.com": 3.0}.get(host, 0.15)
        wait = pause - (time.monotonic() - self.last.get(host, 0))
        if wait > 0:
            self.sleep(wait)
        h = {"User-Agent": self.sec_ua if sec else USER_AGENT, "Accept-Encoding": "gzip"}
        h.update(headers or {})
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(url, data=data, headers=h)
                with urllib.request.urlopen(request, timeout=90) as response:
                    body = response.read()
                    self.last[host] = time.monotonic()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body
            except (urllib.error.URLError, TimeoutError) as exc:
                self.last[host] = time.monotonic()
                code = getattr(exc, "code", None)
                if code is not None and code != 429 and code < 500 or attempt == attempts:
                    raise
                self.sleep((15 if code == 429 else 3) * attempt)

    def json(self, url, **kw):
        return json.loads(self.get(url, **kw))

    def text(self, url):
        return self.get(url).decode("utf-8", "replace")


def attempt(errors, name, fn, default=None):
    try:
        return fn()
    except Exception as exc:  # una fuente caída no tumba las demás: queda registrada
        errors.append({"source": name, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return default


def _folder(cik, accession):
    return f"{SEC_ARCHIVE}/{int(cik)}/{accession.replace('-', '')}"


def _primary_doc_url(http, cik, accession, cache):
    if cik not in cache:
        cache[cik] = http.json(f"{SEC_DATA}/submissions/CIK{cik}.json")["filings"]["recent"]
    recent = cache[cik]
    i = recent["accessionNumber"].index(accession)
    return f"{_folder(cik, accession)}/{recent['primaryDocument'][i]}", recent["form"][i]


def _sha(text):
    return hashlib.sha1(text.encode()).hexdigest()[:10]


# ---------------------------------------------------------------- prompt 1: el libro 13F

def _info_table(http, cik, filing):
    folder = _folder(cik, filing["accession"])
    items = [i["name"] for i in http.json(f"{folder}/index.json")["directory"]["item"]]
    xmls = [n for n in items if n.lower().endswith(".xml") and n != "primary_doc.xml"]
    name = next((n for n in xmls if "infotable" in n.lower()), xmls[0] if xmls else None)
    if not name:
        raise ValueError(f"sin tabla de información en {folder}")
    url = f"{folder}/{name}"
    return url, r.parse_13f_table(http.text(url), filing["filing_date"])


def tickers_for(http, cusips):
    out = {}
    for i in range(0, len(cusips), 10):  # sin clave: 10 por consulta y 25 consultas por minuto
        chunk = cusips[i:i + 10]
        body = json.dumps([{"idType": "ID_CUSIP", "idValue": c} for c in chunk]).encode()
        out.update(r.parse_figi(chunk, http.json(OPENFIGI, data=body, headers={"Content-Type": "application/json"})))
    return out


def collect_book(http, errors, notional=None):
    name, cik = FUND
    filings = r.parse_13f_filings(http.json(f"{SEC_DATA}/submissions/CIK{cik}.json"))
    latest, previous = r.pick_13f(filings)
    if not latest:
        raise ValueError("el fondo no tiene 13F-HR")
    url, holdings = _info_table(http, cik, latest)
    book = r.long_book(holdings)
    prev_book = []
    if previous:
        prev_book = attempt(errors, "13f:previous", lambda: r.long_book(_info_table(http, cik, previous)[1]), [])
    cusips = sorted({b["cusip"] for b in book + prev_book})
    tickers = attempt(errors, "openfigi", lambda: tickers_for(http, cusips), {})
    for row in book + prev_book:
        row["ticker"] = tickers.get(row["cusip"])
    total = sum(b["value_usd"] for b in book)
    changes = r.book_changes(prev_book, book) if prev_book else []
    amendments = [f for f in filings if f["form"] != "13F-HR" and f["report_date"] >= latest["report_date"]]
    label = lambda b: b.get("ticker") or b["issuer"]
    count = lambda kind: [label(c) for c in changes if c["change"] == kind]
    body = (f"{name} · 13F al {latest['report_date']} (presentado {latest['filing_date']}): {len(book)} posiciones "
            f"largas en acciones por {total / 1e9:,.2f} mil M USD. Mayores: "
            + ", ".join(f"{label(b)} {b['weight']:.1%}" for b in book[:5]) + ". "
            + (f"Nuevas: {', '.join(count('NEW')) or 'ninguna'}. Salidas: {', '.join(count('EXIT')) or 'ninguna'}. "
               f"Aumentos: {', '.join(count('ADD')) or 'ninguno'}. " if changes else "")
            + "Calls y puts excluidas. El 13F llega hasta 45 días tarde y no muestra cortos ni posiciones fuera de "
              "EE. UU.: no es el libro de hoy.")
    data = {"fund": name, "cik": cik, "report_date": latest["report_date"], "filing_date": latest["filing_date"],
            "accession": latest["accession"], "source_url": url, "total_long_usd": total,
            "options_excluded_usd": r.options_summary(holdings), "book": book, "changes": changes,
            "previous_report_date": previous["report_date"] if previous else None,
            "amendments": [{k: f[k] for k in ("form", "accession", "filing_date")} for f in amendments],
            "headline": {"positions": len(book), "total_long_usd": total,
                         "top_weight": book[0]["weight"] if book else None}}
    facts = [r.fact_row("13f", "long_value_usd", b.get("ticker") or b["cusip"], latest["report_date"],
                        b["value_usd"], "USD",
                        {"issuer": b["issuer"], "cusip": b["cusip"], "shares": b["shares"], "weight": b["weight"],
                         "accession": latest["accession"]}, url,
                        key=f"13f:{cik}:{latest['report_date']}:{b['cusip']}") for b in book]
    report = r.report_row("13F_BOOK", date.today().isoformat(), f"Libro 13F de {name} al {latest['report_date']}",
                          body, data)
    orders = r.size_orders(book, notional) if notional else None
    return {"facts": facts, "report": report, "orders": orders}


# ---------------------------------------------------------------- prompt 2: la demanda

def company_capex(http, ticker, cik, concepts=CAPEX_CONCEPTS):
    best = None
    for concept in concepts:
        try:
            payload = http.json(f"{SEC_DATA}/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        quarters = r.quarterly_from_ytd(payload["units"].get("USD", []))
        if quarters and (best is None or quarters[-1]["end"] > best[1][-1]["end"]):
            best = (concept, quarters, f"{SEC_DATA}/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json")
    if not best:
        raise ValueError(f"{ticker}: sin capex en XBRL")
    return best


def _quotes(http, errors, ticker, cik, accession, patterns, topic, period_end, cache):
    def run():
        url, form = _primary_doc_url(http, cik, accession, cache)
        texts = r.extract_quotes(http.text(url), patterns)
        facts = [r.fact_row("ai_supply" if topic != "capex" else "ai_demand", "filing_quote", ticker, period_end,
                            None, "text", {"text": t, "topic": topic, "form": form, "accession": accession}, url,
                            key=f"quote:{ticker}:{accession}:{_sha(t)}") for t in texts]
        return {"url": url, "form": form, "quotes": texts}, facts
    return attempt(errors, f"quotes:{ticker}", run, ({"url": None, "quotes": []}, []))


def _capex_block(http, errors, ticker, cik, cache):
    concept, quarters, source = company_capex(http, ticker, cik)
    summary = r.capex_summary(quarters)
    facts = [r.fact_row("ai_demand", "capex_quarter_usd", ticker, q["end"], q["value"], "USD",
                        {"start": q["start"], "concept": concept, "derived": q["derived"], "accession": q["accn"]},
                        source, key=f"capex:{ticker}:{q['end']}") for q in quarters[-8:]]
    filing, quote_facts = _quotes(http, errors, ticker, cik, quarters[-1]["accn"], r.CAPEX_QUOTE, "capex",
                                  quarters[-1]["end"], cache)
    return {"concept": concept, "summary": summary, "quarters": quarters[-8:], "filing": filing}, facts + quote_facts


def collect_demand(http, errors):
    assumptions = json.loads(ASSUMPTIONS.read_text(encoding="utf-8"))
    cache, companies, facts = {}, {}, []
    for ticker, cik in list(BUYERS.items()) + [NVDA]:
        block = attempt(errors, f"capex:{ticker}", lambda: _capex_block(http, errors, ticker, cik, cache))
        if block:
            companies[ticker], more = block
            facts += more
    buyers = [companies[t]["summary"] for t in BUYERS if t in companies and companies[t]["summary"]["ttm_usd"]]
    ttm = sum(s["ttm_usd"] for s in buyers)
    ttm_prev = sum(s["ttm_previous_usd"] for s in buyers if s["ttm_previous_usd"])
    comparable = all(s["ttm_previous_usd"] for s in buyers)
    growth = round((ttm / ttm_prev - 1) * 100, 2) if buyers and comparable and ttm_prev else None
    physical = r.to_physical(ttm, assumptions) if ttm else None
    accel = {t: companies[t]["summary"]["acceleration_pp"] for t in BUYERS if t in companies}
    fastest = max((t for t in accel if accel[t] is not None), key=lambda t: accel[t], default=None)
    lines = [f"{t}: último trimestre {companies[t]['summary']['latest_usd'] / 1e9:,.1f} mil M USD "
             f"(al {companies[t]['summary']['latest_end']}; interanual {companies[t]['summary']['yoy_pct']} %, "
             f"frente al trimestre anterior {companies[t]['summary']['qoq_pct']} %)"
             for t in BUYERS if t in companies]
    body = ("Capex (compra de activo fijo; los informes no separan los centros de datos) de los compradores de IA. "
            + "; ".join(lines) + ". "
            + (f"Suma de los últimos 12 meses: {ttm / 1e9:,.0f} mil M USD ({growth} % interanual). " if ttm else "")
            + (f"Acelera más: {fastest} ({accel[fastest]:+.1f} puntos de crecimiento interanual). " if fastest else "")
            + (f"En cosas físicas (supuestos, no datos): {physical['working']['megawatts']}; "
               f"{physical['working']['hbm_gb']}; {physical['working']['turbines']}." if physical else ""))
    data = {"companies": companies, "aggregate_buyers": {"ttm_usd": ttm, "ttm_growth_pct": growth,
                                                         "companies": [t for t in BUYERS if t in companies]},
            "physical": physical, "assumptions_revised": assumptions.get("revisado"),
            "headline": {"capex_ttm_usd": ttm or None, "capex_ttm_growth_pct": growth,
                         **{f"accel_pp_{t}": v for t, v in accel.items()},
                         "megawatts_mid": physical["megawatts"]["mid"] if physical else None}}
    report = r.report_row("AI_DEMAND", date.today().isoformat(), "Demanda de IA en cosas reales", body[:8000], data)
    return {"facts": facts, "report": report}


# ---------------------------------------------------------------- prompt 3: la oferta

def _months_back(n, today=None):
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}{m:02d}")
    return out


def korea_memory(http, errors, months=KOREA_MONTHS, known=None):
    """Solo pide a Comtrade los meses que el diario aún no tiene (cada consulta tarda 20-30 s)."""
    known = known or {}
    fetched = []
    for period in _months_back(months):
        if f"{period[:4]}-{period[4:]}" in known:
            continue
        fetched += attempt(errors, f"comtrade:{period}",
                           lambda: r.parse_comtrade(http.json(COMTRADE.format(period=period))), [])
    series = {**known, **{s["period"]: s for s in fetched}}
    return [series[k] for k in sorted(series)], fetched


def known_korea(url):
    if "dashboard_reader" not in (url or ""):
        return {}
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                         connect_timeout=15) as conn:
        rows = conn.execute("select to_char(period_end, 'YYYY-MM') as period, value, detail ->> 'net_kg' as net_kg "
                            "from research_facts where metric = 'korea_memory_exports_usd'").fetchall()
    return {row["period"]: {"period": row["period"], "value_usd": float(row["value"]),
                            "net_kg": float(row["net_kg"]) if row["net_kg"] else None} for row in rows}


def _lag_months(period, today=None):
    today = today or date.today()
    y, m = map(int, period.split("-"))
    return (today.year - y) * 12 + today.month - m


def taiwan_orders(http):
    listing = http.text(TAIWAN)
    bull = re.search(r"bull_id=(\d+)", listing).group(1)
    page = http.text(f"{TAIWAN}&bull_id={bull}")
    anchor = page.find("全部附表(ODS")
    file_id = re.search(r"wHandBulletin_File\.ashx\?file_id=(\d+)", page[anchor:]).group(1) if anchor >= 0 else None
    if not file_id:
        raise ValueError("no encontré las tablas ODS en el boletín de Taiwán")
    return r.parse_taiwan_orders_ods(http.get(TAIWAN_FILE.format(file_id=file_id))), f"{TAIWAN}&bull_id={bull}"


def gev_backlog(http, errors, cache):
    _, cik = GEV
    url = f"{SEC_DATA}/api/xbrl/companyconcept/CIK{cik}/us-gaap/{BACKLOG_CONCEPT}.json"
    backlog = r.instant_series(http.json(url)["units"]["USD"])
    concept, revenue, _ = company_capex(http, "GEV", cik, REVENUE_CONCEPTS)
    rev = r.capex_summary(revenue)
    latest = backlog[-1]
    year_ago = next((b for b in backlog if abs((date.fromisoformat(latest["end"]) - date.fromisoformat(b["end"])).days
                                               - 365) <= 20), None)
    filing, quote_facts = _quotes(http, errors, "GEV", cik, latest["accn"], r.TURBINE_QUOTE, "turbines",
                                  latest["end"], cache)
    facts = [r.fact_row("ai_supply", "remaining_performance_obligation_usd", "GEV", b["end"], b["value"], "USD",
                        {"accession": b["accn"]}, url, key=f"rpo:GEV:{b['end']}") for b in backlog[-8:]]
    return {"backlog_usd": latest["value"], "backlog_end": latest["end"],
            "backlog_yoy_pct": r._pct(latest["value"], year_ago["value"] if year_ago else None),
            "revenue_ttm_usd": rev["ttm_usd"],
            "backlog_years": round(latest["value"] / rev["ttm_usd"], 2) if rev["ttm_usd"] else None,
            "note": "Cartera total de GE Vernova (gas, red y eólica): el 10-Q no la separa en XBRL; las frases citadas "
                    "dan el detalle de gas.", "filing": filing}, facts + quote_facts


def micron(http, errors, cache):
    ticker, cik = MU
    concept, quarters, source = company_capex(http, ticker, cik)
    filing, quote_facts = _quotes(http, errors, ticker, cik, quarters[-1]["accn"], r.HBM_QUOTE, "hbm",
                                  quarters[-1]["end"], cache)
    facts = [r.fact_row("ai_supply", "capex_quarter_usd", ticker, q["end"], q["value"], "USD",
                        {"concept": concept, "derived": q["derived"], "accession": q["accn"]}, source,
                        key=f"capex:{ticker}:{q['end']}") for q in quarters[-8:]]
    return {"capex": r.capex_summary(quarters), "filing": filing}, facts + quote_facts


def collect_supply(http, errors, korea_months=KOREA_MONTHS, known=None):
    cache, facts = {}, []
    korea, fetched = korea_memory(http, errors, korea_months, known)
    korea_yoy = r.yoy_by_period(korea, "value_usd")
    korea_kg_yoy = r.yoy_by_period(korea, "net_kg")
    facts += [r.fact_row("ai_supply", "korea_memory_exports_usd", "KOR", f"{s['period']}-01", s["value_usd"], "USD",
                         {"net_kg": s["net_kg"], "hs": "854232"}, COMTRADE.format(period=s["period"].replace("-", "")),
                         key=f"kr_memory:{s['period']}") for s in fetched]
    tw = attempt(errors, "taiwan", lambda: taiwan_orders(http), ([], None))
    tw_rows, tw_url = tw
    for row in tw_rows[-24:]:
        for part in ("total", "ict", "electronics"):
            facts.append(r.fact_row("ai_supply", f"taiwan_export_orders_{part}_usd", "TWN", f"{row['period']}-01",
                                    row[f"{part}_usd"], "USD", {"yoy_pct": row[f"{part}_yoy_pct"]}, tw_url,
                                    key=f"tw_orders:{row['period']}:{part}"))
    gev = attempt(errors, "gev", lambda: gev_backlog(http, errors, cache))
    mu = attempt(errors, "micron", lambda: micron(http, errors, cache))
    for block in (gev, mu):
        if block:
            facts += block[1]
    k_last = korea[-1] if korea else None
    t_last = tw_rows[-1] if tw_rows else None
    g = gev[0] if gev else None
    m = mu[0] if mu else None
    headline = {
        "korea_memory_latest_period": k_last["period"] if k_last else None,
        "korea_memory_yoy_pct": korea_yoy.get(k_last["period"]) if k_last else None,
        "korea_memory_kg_yoy_pct": korea_kg_yoy.get(k_last["period"]) if k_last else None,
        "korea_memory_lag_months": _lag_months(k_last["period"]) if k_last else None,
        "taiwan_latest_period": t_last["period"] if t_last else None,
        "taiwan_ict_yoy_pct": t_last["ict_yoy_pct"] if t_last else None,
        "taiwan_electronics_yoy_pct": t_last["electronics_yoy_pct"] if t_last else None,
        "gev_backlog_usd": g["backlog_usd"] if g else None,
        "gev_backlog_yoy_pct": g["backlog_yoy_pct"] if g else None,
        "gev_backlog_years": g["backlog_years"] if g else None,
        "micron_capex_ttm_growth_pct": m["capex"]["ttm_growth_pct"] if m else None,
    }
    fmt = lambda v, suffix=" %": "sin dato" if v is None else f"{v:+.1f}{suffix}"
    body = (f"Corea, exportaciones de memorias (SA 854232, Comtrade): último mes {headline['korea_memory_latest_period']} "
            f"({headline['korea_memory_lag_months']} meses de retraso), valor {fmt(headline['korea_memory_yoy_pct'])} y "
            f"peso {fmt(headline['korea_memory_kg_yoy_pct'])} interanual. "
            f"Taiwán, pedidos de exportación de {headline['taiwan_latest_period']}: información y comunicaciones "
            f"{fmt(headline['taiwan_ict_yoy_pct'])}, electrónica {fmt(headline['taiwan_electronics_yoy_pct'])} interanual. "
            + (f"GE Vernova, cartera pendiente {g['backlog_usd'] / 1e9:,.1f} mil M USD ({fmt(g['backlog_yoy_pct'])} "
               f"interanual; {g['backlog_years']} años de ingresos). " if g else "")
            + (f"Micron, capex de 12 meses {fmt(m['capex']['ttm_growth_pct'])} interanual. " if m else "")
            + "Cola de conexión a la red: sin fuente mensual gratuita legible por máquina; se cita a mano en el "
              "informe de cuello de botella.")
    data = {"korea_memory": {"series": korea, "yoy_pct": korea_yoy, "kg_yoy_pct": korea_kg_yoy,
                             "source": "https://comtradeplus.un.org (API pública, reporterCode 410, SA 854232)"},
            "taiwan_orders": {"rows": tw_rows[-24:], "source_url": tw_url},
            "gas_turbines": g, "memory_maker": m,
            "grid_queue": {"status": "sin fuente automática", "note": "ERCOT y LBNL publican la cola en PDF o en informes "
                           "anuales: el informe AI_BOTTLENECK la cita con enlace si la usa."},
            "headline": headline}
    report = r.report_row("AI_SUPPLY", date.today().isoformat(), "Oferta física para la IA", body[:8000], data)
    return {"facts": facts, "report": report}


# ---------------------------------------------------------------- diario

def previous_reports(url):
    if "dashboard_reader" not in (url or ""):
        return {}
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                         connect_timeout=15) as conn:
        rows = conn.execute("select kind, report_key, data from v_research_latest").fetchall()
    return {row["kind"]: row for row in rows}


def insert(url, facts, reports, agent_id="claude"):
    import psycopg
    with psycopg.connect(url, autocommit=True, prepare_threshold=None, connect_timeout=15) as conn:
        counts = [conn.execute(sql).rowcount for sql in r.to_sql_statements(facts, reports, agent_id)]
    names = (["facts"] if facts else []) + (["reports"] if reports else [])
    return dict(zip(names, counts))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=("book", "demand", "supply", "all"))
    parser.add_argument("--notional", type=float, help="monto para la lista de órdenes hipotética del libro 13F")
    parser.add_argument("--insert", action="store_true", help="escribe con INGEST_DATABASE_URL (rol lab_ingest)")
    parser.add_argument("--out", help="archivo JSON (UTF-8) con todos los datos")
    parser.add_argument("--korea-months", type=int, default=KOREA_MONTHS)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    env = load_env()
    http = Http(env.get("SEC_USER_AGENT"))
    errors, results = [], {}
    steps = {"book": lambda: collect_book(http, errors, args.notional),
             "demand": lambda: collect_demand(http, errors),
             "supply": lambda: collect_supply(http, errors, args.korea_months,
                                              attempt(errors, "known_korea",
                                                      lambda: known_korea(env.get("DASHBOARD_DATABASE_URL")), {}))}
    for name in (steps if args.what == "all" else [args.what]):
        out = attempt(errors, name, steps[name])
        if out:
            results[name] = out

    previous = attempt(errors, "previous_reports", lambda: previous_reports(env.get("DASHBOARD_DATABASE_URL")), {})
    for out in results.values():
        report = out["report"]
        before = previous.get(report["kind"])
        if before and before["report_key"] != report["report_key"]:
            report["data"]["comparison"] = {"previous_report_key": before["report_key"],
                                            **r.compare_headlines(before["data"], report["data"])}
    facts = [f for out in results.values() for f in out["facts"]]
    reports = [out["report"] for out in results.values()]
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "facts": len(facts), "errors": errors,
               "reports": {rep["kind"]: {"title": rep["title"], "body": rep["body"],
                                         "headline": rep["data"].get("headline"),
                                         "comparison": rep["data"].get("comparison")} for rep in reports}}
    if "book" in results and results["book"]["orders"]:
        summary["hypothetical_orders"] = {"notional_usd": args.notional, "orders": results["book"]["orders"],
                                          "note": "Hipotético: no se envía ninguna orden. Precio implícito al cierre "
                                                  "del trimestre del 13F, no un precio actual."}
    if args.insert:
        url = env.get("INGEST_DATABASE_URL", "")
        if "lab_ingest" not in url:
            sys.exit("Falta INGEST_DATABASE_URL con el rol lab_ingest en .env")
        summary["inserted"] = insert(url, facts, reports)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "facts": facts, "reports": reports}, f, ensure_ascii=False, indent=1,
                      default=str)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
