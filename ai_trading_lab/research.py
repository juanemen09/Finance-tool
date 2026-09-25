"""Tesis de infraestructura de IA: el libro 13F de un fondo, el capex de los compradores y la oferta física.

Solo transforma datos ya descargados (lo prueba todo sin red); la descarga está en tools/ai_research.py.
Nada de esto es una señal validada ni se opera aquí: es investigación que se informa al usuario.
"""
import hashlib
import io
import json
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html.parser import HTMLParser

from ai_trading_lab.sentiment import AGENT_ID, _dollar_quote

# Desde el 2023-01-03 el 13F da el valor en dólares; antes, en miles.
THIRTEEN_F_DOLLARS_FROM = "2023-01-03"
QUARTER_DAYS = range(80, 101)
FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")
TOPICS = ("13f", "ai_demand", "ai_supply")
REPORT_KINDS = ("13F_BOOK", "AI_DEMAND", "AI_SUPPLY", "AI_BOTTLENECK")


# ---------------------------------------------------------------- 13F

def parse_13f_filings(submissions):
    recent = submissions["filings"]["recent"]
    out = []
    for i, form in enumerate(recent["form"]):
        if form.startswith("13F-HR"):
            out.append({"form": form, "accession": recent["accessionNumber"][i],
                        "filing_date": recent["filingDate"][i], "report_date": recent["reportDate"][i],
                        "primary_document": recent["primaryDocument"][i]})
    return sorted(out, key=lambda f: (f["report_date"], f["filing_date"]), reverse=True)


def pick_13f(filings):
    """El original más reciente y el del trimestre anterior. Las enmiendas (13F-HR/A) pueden ser solo añadidos:
    se listan aparte en el informe en lugar de mezclarse."""
    originals = [f for f in filings if f["form"] == "13F-HR"]
    latest = originals[0] if originals else None
    previous = next((f for f in originals if latest and f["report_date"] < latest["report_date"]), None)
    return latest, previous


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(node, name):
    for c in node:
        if _local(c.tag) == name:
            return c
    return None


def _text(node, *path):
    for name in path:
        node = _child(node, name) if node is not None else None
    return node.text.strip() if node is not None and node.text else None


def parse_13f_table(xml_text, filing_date):
    root = ET.fromstring(xml_text)
    scale = 1 if filing_date >= THIRTEEN_F_DOLLARS_FROM else 1000
    out = []
    for node in root.iter():
        if _local(node.tag) != "infoTable":
            continue
        out.append({
            "issuer": _text(node, "nameOfIssuer"),
            "title_of_class": _text(node, "titleOfClass"),
            "cusip": _text(node, "cusip"),
            "value_usd": int(float(_text(node, "value"))) * scale,
            "shares": int(float(_text(node, "shrsOrPrnAmt", "sshPrnamt"))),
            "share_type": _text(node, "shrsOrPrnAmt", "sshPrnamtType"),
            "put_call": _text(node, "putCall"),
        })
    return out


def long_book(holdings):
    """Solo acciones en largo (sin calls ni puts), una fila por CUSIP, con su peso en el libro."""
    merged = {}
    for h in holdings:
        if h["put_call"] or h["share_type"] != "SH":
            continue
        row = merged.setdefault(h["cusip"], {"cusip": h["cusip"], "issuer": h["issuer"],
                                             "title_of_class": h["title_of_class"], "shares": 0, "value_usd": 0})
        row["shares"] += h["shares"]
        row["value_usd"] += h["value_usd"]
    total = sum(r["value_usd"] for r in merged.values())
    book = sorted(merged.values(), key=lambda r: r["value_usd"], reverse=True)
    for row in book:
        row["weight"] = row["value_usd"] / total if total else 0.0
        # Precio implícito al cierre del trimestre del 13F: no es un precio actual.
        row["implied_price"] = row["value_usd"] / row["shares"] if row["shares"] else None
    return book


def options_summary(holdings):
    out = {}
    for h in holdings:
        if h["put_call"]:
            key = h["put_call"].lower()
            out[key] = out.get(key, 0) + h["value_usd"]
    return out


def book_changes(previous, current):
    prev = {r["cusip"]: r for r in previous}
    cur = {r["cusip"]: r for r in current}
    out = []
    for cusip in list(cur) + [c for c in prev if c not in cur]:
        a, b = prev.get(cusip), cur.get(cusip)
        before, after = (a or {}).get("shares", 0), (b or {}).get("shares", 0)
        if not a:
            change = "NEW"
        elif not b:
            change = "EXIT"
        else:
            change = "ADD" if after > before else "TRIM" if after < before else "SAME"
        out.append({"cusip": cusip, "issuer": (b or a)["issuer"], "ticker": (b or a).get("ticker"),
                    "change": change, "shares_previous": before, "shares_current": after,
                    "shares_change_pct": round((after / before - 1) * 100, 2) if before and after else None})
    return out


def size_orders(book, notional):
    """Lista de órdenes HIPOTÉTICA: los mismos pesos contra un monto. No se envía nada a ningún sitio."""
    if not notional or notional <= 0:
        raise ValueError("el monto debe ser positivo")
    out = []
    for row in book:
        amount = round(row["weight"] * notional, 2)
        price = row.get("implied_price")
        shares = math.floor(amount / price * 10_000) / 10_000 if price else None
        out.append({"cusip": row["cusip"], "ticker": row.get("ticker"), "issuer": row["issuer"],
                    "weight": row["weight"], "amount_usd": amount, "implied_price": price, "approx_shares": shares})
    return out


def parse_figi(cusips, response):
    out = {}
    for cusip, job in zip(cusips, response):
        # Solo el ticker de EE. UU.: el de otra bolsa ("1B2" en Fráncfort) confunde más que el nombre del emisor.
        us = [d for d in job.get("data", []) if d.get("ticker") and d.get("exchCode") == "US"]
        if us:
            out[cusip] = us[0]["ticker"]
    return out


# ---------------------------------------------------------------- capex (XBRL de la SEC)

def _d(text):
    return date.fromisoformat(text)


def _latest_filed(facts, key):
    best = {}
    for f in facts:
        k = key(f)
        if k not in best or f["filed"] > best[k]["filed"]:
            best[k] = f
    return best


def quarterly_from_ytd(units):
    """Trimestres sueltos desde el flujo de caja, que en los 10-Q es acumulado del año (3, 6, 9 y 12 meses):
    cada trimestre es la resta de dos acumulados consecutivos con el mismo inicio."""
    facts = [f for f in units if f.get("start") and f.get("form") in FORMS]
    latest = _latest_filed(facts, lambda f: (f["start"], f["end"]))
    quarters = {}

    def put(start, end, value, derived, f):
        if end not in quarters or quarters[end]["derived"] and not derived:
            quarters[end] = {"start": start, "end": end, "value": value, "derived": derived,
                             "accn": f["accn"], "form": f["form"]}

    by_start = {}
    for f in latest.values():
        by_start.setdefault(f["start"], []).append(f)
        if (_d(f["end"]) - _d(f["start"])).days + 1 in QUARTER_DAYS:
            put(f["start"], f["end"], f["val"], False, f)
    for group in by_start.values():
        group.sort(key=lambda f: f["end"])
        for a, b in zip(group, group[1:]):
            if (_d(b["end"]) - _d(a["end"])).days in QUARTER_DAYS:
                start = (_d(a["end"]) + timedelta(days=1)).isoformat()
                put(start, b["end"], b["val"] - a["val"], True, b)
    return [quarters[k] for k in sorted(quarters)]


def instant_series(units):
    """Saldos a una fecha (p. ej. la cartera de pedidos pendientes): uno por fecha, el último presentado."""
    facts = [f for f in units if not f.get("start") and f.get("form") in FORMS]
    latest = _latest_filed(facts, lambda f: f["end"])
    return [{"end": k, "value": latest[k]["val"], "accn": latest[k]["accn"]} for k in sorted(latest)]


def _pct(a, b):
    return round((a / b - 1) * 100, 2) if a is not None and b else None


def _year_before(quarters, end):
    target = _d(end) - timedelta(days=365)
    near = [q for q in quarters if abs((_d(q["end"]) - target).days) <= 20]
    return near[0] if near else None


def capex_summary(quarters):
    if not quarters:
        return None
    latest = quarters[-1]
    prev = quarters[-2] if len(quarters) > 1 else None
    ago = _year_before(quarters, latest["end"])
    prev_ago = _year_before(quarters, prev["end"]) if prev else None
    yoy = _pct(latest["value"], ago["value"] if ago else None)
    yoy_prev = _pct(prev["value"], prev_ago["value"] if prev_ago else None) if prev else None
    ttm = sum(q["value"] for q in quarters[-4:]) if len(quarters) >= 4 else None
    ttm_prev = sum(q["value"] for q in quarters[-8:-4]) if len(quarters) >= 8 else None
    return {
        "latest_end": latest["end"], "latest_usd": latest["value"],
        "previous_usd": prev["value"] if prev else None,
        "qoq_pct": _pct(latest["value"], prev["value"] if prev else None),
        "yoy_pct": yoy, "yoy_pct_previous_quarter": yoy_prev,
        "acceleration_pp": round(yoy - yoy_prev, 2) if yoy is not None and yoy_prev is not None else None,
        "ttm_usd": ttm, "ttm_previous_usd": ttm_prev, "ttm_growth_pct": _pct(ttm, ttm_prev),
    }


# ---------------------------------------------------------------- citas textuales de los informes

class _Text(HTMLParser):
    SKIP = {"script", "style", "ix:header"}
    BLOCK = {"p", "div", "td", "th", "tr", "li", "br", "table", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        # Los saltos de línea del código fuente no separan frases: solo las etiquetas de bloque.
        if not self.skip:
            self.parts.append(data.replace("\n", " "))


def html_text(html):
    parser = _Text()
    parser.feed(html)
    return "".join(parser.parts)


NEVER = re.compile(r"(?!x)x")
NUMBER = re.compile(r"\$\s?\d|\d(\.\d+)?\s?(%|percent|billion|gigawatts?|GW)\b", re.I)
CHANGE = r"\b(increase[ds]?|decrease[ds]?|grew|growth|higher|lower|driven by|due to|as a result)\b"
# (tema principal, tema secundario, cambio). Entra una frase con cambio y tema principal, o con tema secundario
# y una cifra: así "arrendamos centros de datos" no pasa por explicación del capex.
CAPEX_QUOTE = (re.compile(r"capital expenditures?|property and equipment|purchases of property|additions to property",
                          re.I),
               re.compile(r"data cent(er|re)s?|AI infrastructure|technical infrastructure|servers", re.I),
               re.compile(CHANGE, re.I))
TURBINE_QUOTE = (re.compile(r"gas power|gas turbines?|heavy[- ]duty|slot reservations?", re.I), NEVER,
                 re.compile(r"\b(backlog|slot reservations?|gigawatts?|GW|orders|increase[ds]?|grew)\b", re.I))
HBM_QUOTE = (re.compile(r"\bHBM\b|high[- ]bandwidth memory", re.I), NEVER,
             re.compile(r"\b(sold out|supply|capacity|demand|tight|constrain\w*|allocat\w*)\b", re.I))


TERMINAL = (".", "!", "?", ".”", '."', ".)")


def _paragraphs(text):
    """Bloques de texto, uniendo los párrafos que un salto de página del informe partió en dos: un bloque largo
    sin punto final continúa en el siguiente."""
    out = []
    for block in text.split("\n"):
        block = " ".join(block.split())
        if not block:
            continue
        if out and len(out[-1]) >= 80 and not out[-1].endswith((".", "!", "?", ":", ";", "”", '"', ")")):
            out[-1] = f"{out[-1]} {block}"
        else:
            out.append(block)
    return out


def extract_quotes(html, spec, max_quotes=3, max_len=600):
    """Frases TEXTUALES del informe sobre el tema y su cambio, las más concretas primero (tema principal y cifras).
    Nada se resume ni se reescribe."""
    primary, secondary, change = spec
    scored, seen = [], set()
    for block in _paragraphs(html_text(html)):
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", block):
            # Una frase sin punto final es un trozo (celda, título o corte): citarla la tergiversaría.
            if not 60 <= len(sentence) <= max_len or sentence in seen or not change.search(sentence) \
                    or not sentence.endswith(TERMINAL):
                continue
            main, extra, number = (bool(primary.search(sentence)), bool(secondary.search(sentence)),
                                   bool(NUMBER.search(sentence)))
            if main or (extra and number):
                seen.add(sentence)
                scored.append((3 * main + extra + 2 * number, -len(scored), sentence))
    return [s for *_, s in sorted(scored, reverse=True)[:max_quotes]]


# ---------------------------------------------------------------- dólares → cosas físicas (supuestos)

def to_physical(capex_usd, a):
    """Rangos, no datos: cada número sale de supuestos con fuente (config/ai_infra_assumptions.json)."""
    share, cost, gb, pue, sqft = (a["datacenter_share"], a["cost_per_mw_usd"], a["hbm_gb_per_it_mw"], a["pue"],
                                  a["sqft_per_mw"])
    mw = {"low": capex_usd * share["low"] / cost["high"], "mid": capex_usd * share["mid"] / cost["mid"],
          "high": capex_usd * share["high"] / cost["low"]}
    out = {
        "megawatts": mw,
        # Memoria HBM de las GPU: MW de la instalación → MW de TI (÷ PUE) → GB por MW de TI.
        "hbm_gb": {"low": mw["low"] / pue["high"] * gb["low"], "mid": mw["mid"] / pue["mid"] * gb["mid"],
                   "high": mw["high"] / pue["low"] * gb["high"]},
        "square_feet": {k: mw[k] * sqft[k] for k in mw},
        "heavy_duty_turbines": {k: mw[k] / a["turbine_mw"]["heavy_duty"] for k in mw},
        "aeroderivative_turbines": {k: mw[k] / a["turbine_mw"]["aeroderivative"] for k in mw},
    }
    b = capex_usd / 1e9
    out["working"] = {
        "megawatts": f"{b:,.1f} mil M USD × {share['mid']:.0%} en centros de datos ÷ {cost['mid'] / 1e6:,.0f} M USD "
                     f"por MW = {mw['mid']:,.0f} MW (rango {mw['low']:,.0f}–{mw['high']:,.0f})",
        "hbm_gb": f"{mw['mid']:,.0f} MW ÷ PUE {pue['mid']} × {gb['mid']:,.0f} GB de HBM por MW de TI "
                  f"= {out['hbm_gb']['mid'] / 1e6:,.1f} M GB",
        "square_feet": f"{mw['mid']:,.0f} MW × {sqft['mid']:,.0f} pies² por MW = {out['square_feet']['mid'] / 1e6:,.1f} M pies²",
        "turbines": f"{mw['mid']:,.0f} MW ÷ {a['turbine_mw']['heavy_duty']} MW por turbina de ciclo simple grande "
                    f"= {out['heavy_duty_turbines']['mid']:,.0f} (equivalencia si toda esa potencia fuera gas nuevo)",
    }
    return out


# ---------------------------------------------------------------- oferta: Corea (Comtrade) y Taiwán (MOEA)

def parse_comtrade(payload):
    """Exportaciones de Corea al mundo del código SA pedido (854232 = circuitos integrados de memoria)."""
    out = []
    for row in payload.get("data", []):
        if row.get("flowCode") == "X" and row.get("partnerCode") == 0:
            p = str(row["period"])
            out.append({"period": f"{p[:4]}-{p[4:6]}", "value_usd": float(row["primaryValue"]),
                        "net_kg": float(row["netWgt"]) if row.get("netWgt") is not None else None})
    return out


def yoy_by_period(series, key):
    by = {s["period"]: s[key] for s in series if s.get(key) is not None}
    out = {}
    for period, value in by.items():
        y, m = period.split("-")
        before = by.get(f"{int(y) - 1}-{m}")
        if before:
            out[period] = round((value / before - 1) * 100, 2)
    return out


ODS_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
ODS_X = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODS_O = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
YI = 1e8  # 億 = cien millones


def _ods_rows(table):
    for row in table.iter(f"{ODS_T}table-row"):
        cells = []
        for c in row:
            if c.tag not in (f"{ODS_T}table-cell", f"{ODS_T}covered-table-cell"):
                continue
            repeat = min(int(c.get(f"{ODS_T}number-columns-repeated", "1")), 20)
            value = c.get(f"{ODS_O}value") or "".join("".join(p.itertext()) for p in c.iter(f"{ODS_X}p"))
            cells += [value.strip()] * repeat
        yield cells


def parse_taiwan_orders_ods(content):
    """Tabla 2 del boletín de pedidos de exportación: total, información y comunicaciones, y electrónica, en USD.
    Los años vienen en calendario de la República de China (115 = 2026)."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        # Un ODS de verdad pesa kilobytes: un content.xml enorme sería un archivo roto o una bomba de compresión.
        if z.getinfo("content.xml").file_size > 50_000_000:
            raise ValueError("content.xml demasiado grande")
        root = ET.fromstring(z.read("content.xml"))
    table = next(t for t in root.iter(f"{ODS_T}table") if t.get(f"{ODS_T}name") == "表2p1")
    out, year = [], None
    for cells in _ods_rows(table):
        cells += [""] * (8 - len(cells))
        y = re.fullmatch(r"(\d+)年", cells[0])
        if y:
            year = int(y.group(1)) + 1911
        elif cells[0]:
            continue  # "115年1-8月", "較上月增減"...: acumulados y variaciones, no meses
        m = re.fullmatch(r"(\d+)月", cells[1])
        if not (m and year):
            continue
        num = lambda i: float(cells[i]) if re.fullmatch(r"-?\d+(\.\d+)?", cells[i]) else None
        out.append({"period": f"{year}-{int(m.group(1)):02d}",
                    "total_usd": num(2) * YI, "total_yoy_pct": num(3),
                    "ict_usd": num(4) * YI, "ict_yoy_pct": num(5),
                    "electronics_usd": num(6) * YI, "electronics_yoy_pct": num(7)})
    return out


# ---------------------------------------------------------------- filas para el diario

def fact_row(topic, metric, entity, period_end, value, unit, detail, source_url, key):
    if topic not in TOPICS:
        raise ValueError(f"tema no válido: {topic}")
    if not source_url.startswith("https://"):
        raise ValueError("la fuente debe ser https")
    return {"fact_key": key, "topic": topic, "metric": metric, "entity": entity, "period_end": period_end,
            "value": value, "unit": unit, "detail": detail, "source_url": source_url}


def report_row(kind, as_of, title, body, data):
    if kind not in REPORT_KINDS:
        raise ValueError(f"tipo de informe no válido: {kind}")
    # La comparación con el informe anterior no cuenta: si no, repetir la ejecución crearía un informe "nuevo".
    hashed = {k: v for k, v in data.items() if k != "comparison"}
    digest = hashlib.sha256(json.dumps(hashed, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {"report_key": f"{kind}:{digest}", "kind": kind, "as_of": as_of, "title": title, "body": body,
            "data": data}


def compare_headlines(previous, current):
    prev, cur = (previous or {}).get("headline", {}), (current or {}).get("headline", {})
    out = {}
    for key, value in cur.items():
        before = prev.get(key)
        out[key] = {"previous": before, "current": value,
                    "change": round(value - before, 4) if value is not None and before is not None else None}
    return out


def to_sql_statements(facts, reports, agent_id):
    if not AGENT_ID.match(agent_id):
        raise ValueError(f"agent_id no válido: {agent_id!r}")
    statements = []
    if facts:
        payload = _dollar_quote(json.dumps(facts, ensure_ascii=False, default=str))
        statements.append(
            "insert into public.research_facts (fact_key, topic, metric, entity, period_end, value, unit, detail, "
            "source_url, recorded_by_agent_id)\n"
            f"select fact_key, topic, metric, entity, period_end, value, unit, coalesce(detail, '{{}}'), source_url, "
            f"'{agent_id}'\n"
            f"from jsonb_to_recordset({payload}::jsonb) as x(fact_key text, topic text, metric text, entity text, "
            "period_end date, value numeric, unit text, detail jsonb, source_url text)\non conflict do nothing;")
    if reports:
        payload = _dollar_quote(json.dumps(reports, ensure_ascii=False, default=str))
        statements.append(
            "insert into public.research_reports (report_key, kind, as_of, title, body, data, recorded_by_agent_id)\n"
            f"select report_key, kind, as_of, title, body, data, '{agent_id}'\n"
            f"from jsonb_to_recordset({payload}::jsonb) as x(report_key text, kind text, as_of date, title text, "
            "body text, data jsonb)\non conflict do nothing;")
    return statements
