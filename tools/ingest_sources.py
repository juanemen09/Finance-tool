"""Papers recientes de arXiv (q-fin) sobre estrategias de trading, para que el agente los clasifique.

La salida incluye el abstract solo para que el agente lo lea; en Supabase se guarda un resumen propio,
nunca el texto original.

Uso:  python -m tools.ingest_sources --since 2026-09-01 [--exclude known_keys.json] [--max 50]
"""
import argparse
import gzip
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API = "https://export.arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
CATEGORIES = ["q-fin.TR", "q-fin.PM", "q-fin.ST", "q-fin.CP"]
DEFAULT_TERMS = ["cryptocurrency", "bitcoin", "crypto"]


def build_query(terms):
    cats = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    words = " OR ".join(f'abs:"{t}"' for t in terms)
    return f"({cats}) AND ({words})"


def parse_feed(xml_text):
    root = ET.fromstring(xml_text)
    papers = []
    for entry in root.findall("a:entry", ATOM):
        raw_id = entry.findtext("a:id", default="", namespaces=ATOM).rsplit("/abs/", 1)[-1]
        arxiv_id = raw_id.split("v")[0] if "v" in raw_id else raw_id
        papers.append({
            "source_key": f"arxiv:{arxiv_id}",
            "source": "arxiv",
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "title": " ".join(entry.findtext("a:title", default="", namespaces=ATOM).split()),
            "authors": [a.findtext("a:name", default="", namespaces=ATOM) for a in entry.findall("a:author", ATOM)],
            "published_at": entry.findtext("a:published", default="", namespaces=ATOM)[:10],
            "abstract_for_reading_only": " ".join(entry.findtext("a:summary", default="", namespaces=ATOM).split()),
        })
    return papers


def fetch(terms, max_results):
    params = {"search_query": build_query(terms), "sortBy": "submittedDate", "sortOrder": "descending",
              "max_results": max_results}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    # arXiv responde 406 a urllib con Accept-Encoding: identity (su valor por defecto); con gzip responde 200.
    request = urllib.request.Request(url, headers={"User-Agent": "ai-trading-lab/1.0 (research ingestion)",
                                                   "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return parse_feed(body.decode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="AAAA-MM-DD: solo papers publicados desde esa fecha")
    parser.add_argument("--exclude", help="JSON con una lista de source_key ya registrados")
    parser.add_argument("--terms", nargs="*", default=DEFAULT_TERMS)
    parser.add_argument("--max", type=int, default=50)
    args = parser.parse_args()
    known = set(json.load(open(args.exclude, encoding="utf-8"))) if args.exclude else set()
    papers = [p for p in fetch(args.terms, args.max) if p["published_at"] >= args.since and p["source_key"] not in known]
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(papers, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
