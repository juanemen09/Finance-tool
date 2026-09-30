"""Predicciones fuera del trading: preguntas libres que se responden con datos públicos y TimesFM 3.0.

Nada de aquí toca el diario de Supabase, las estrategias ni la prueba de TimesFM del trading: las preguntas y respuestas
viven solo en data/predicciones/ (fuera de git), y el modo TV las muestra en su sección «Predicciones».

  python -m tools.predicciones pendientes                 preguntas sin responder
  python -m tools.predicciones enso-sierra --out DIR      datos de El Niño y lluvia de la sierra (CSV + estadística)
  python -m tools.predicciones guardar RESULTADO.json     guarda una respuesta (la valida antes)

Flujo: el usuario pregunta en la TV o en el chat; Claude busca las series públicas que responden la pregunta, las
pronostica con TimesFM (herramienta MCP `timesfm`) y guarda la respuesta con sus fuentes y sus límites.
"""
import argparse
import csv
import json
import statistics
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "predicciones"
UA = {"User-Agent": "ai-trading-lab-predicciones/1.0 (investigacion personal)"}
NINO_URL = "https://www.cpc.ncep.noaa.gov/data/indices/ersst5.nino.mth.91-20.ascii"
POWER_URL = ("https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=PRECTOTCORR&community=AG"
             "&longitude={lon}&latitude={lat}&start=1981&end={end}&format=JSON")
SIERRA = {"Quito": (-0.18, -78.47), "Riobamba": (-1.67, -78.65), "Cuenca": (-2.90, -79.00)}
DAYS = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
MAX_QUESTION = 500


# ---------------------------------------------------------------- preguntas y respuestas
def add_request(question, source="tv", now=None):
    q = " ".join(str(question).split())[:MAX_QUESTION]
    if len(q) < 8:
        raise ValueError("La pregunta es demasiado corta.")
    item = {"id": uuid.uuid4().hex[:10], "question": q, "source": source,
            "created_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / "requests.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def load_all(base=None):
    base = Path(base or DATA)
    requests = []
    try:
        for line in (base / "requests.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                requests.append(json.loads(line))
    except FileNotFoundError:
        pass
    results = {}
    for path in sorted((base / "results").glob("*.json")) if (base / "results").exists() else []:
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
            results[r["id"]] = r
        except (ValueError, KeyError):
            continue
    for r in requests:
        r["status"] = "respondida" if r["id"] in results else "pendiente"
    return {"requests": list(reversed(requests))[:30],
            "results": sorted(results.values(), key=lambda r: r.get("answered_at", ""), reverse=True)[:10]}


REQUIRED = {"id", "question", "summary", "series", "sources", "caveats"}


def save_result(result, base=None):
    """Valida la forma de la respuesta antes de guardarla: la TV confía en ella."""
    missing = REQUIRED - set(result)
    if missing:
        raise ValueError(f"faltan campos: {sorted(missing)}")
    if not all(s.get("name") and isinstance(s.get("history"), list) for s in result["series"]):
        raise ValueError("cada serie necesita name e history")
    if not all(str(src.get("url", "")).startswith("https://") for src in result["sources"]):
        raise ValueError("las fuentes deben ser enlaces https")
    result.setdefault("answered_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    out = Path(base or DATA) / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{result['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return out / f"{result['id']}.json"


# ---------------------------------------------------------------- receta: El Niño y la sierra ecuatoriana
def parse_nino(text):
    """Anomalía mensual Niño 3.4 (°C, base 1991-2020): [(año, mes, anomalía)]."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 10 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1]), float(parts[9])))
    return rows


def parse_power(payload):
    """Lluvia mensual (mm/mes) de NASA POWER: {(año, mes): mm}. Omite los promedios anuales (mes 13) y huecos."""
    out = {}
    for key, value in payload["properties"]["parameter"]["PRECTOTCORR"].items():
        year, month = int(key[:4]), int(key[4:])
        if 1 <= month <= 12 and value is not None and value >= 0:
            out[(year, month)] = value * DAYS[month - 1]
    return out


def anomalies(series):
    """Anomalía respecto del promedio de ese mes del año (quita la estacionalidad)."""
    by_month = {}
    for (y, m), v in series.items():
        by_month.setdefault(m, []).append(v)
    clim = {m: statistics.mean(v) for m, v in by_month.items()}
    return {k: v - clim[k[1]] for k, v in series.items()}, clim


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    return statistics.correlation(xs, ys)


def enso_sierra_stats(nino, rains, strong=1.5):
    """Para cada ciudad: correlación entre Niño 3.4 y la anomalía de lluvia (mismo mes y con 1-3 meses de retraso) y
    cuánto cambió la lluvia, por estación, en los meses de El Niño fuerte."""
    nino_map = {(y, m): a for y, m, a in nino}
    stats = {}
    for city, rain in rains.items():
        anom, clim = anomalies(rain)
        lagged = {}
        for lag in (0, 1, 2, 3):
            pairs = []
            for (y, m), a in anom.items():
                ly, lm = (y, m - lag) if m - lag >= 1 else (y - 1, m - lag + 12)
                if (ly, lm) in nino_map:
                    pairs.append((nino_map[(ly, lm)], a))
            lagged[lag] = round(pearson([p[0] for p in pairs], [p[1] for p in pairs]) or 0, 3)
        seasons = {"dic-feb": (12, 1, 2), "mar-may": (3, 4, 5), "jun-ago": (6, 7, 8), "sep-nov": (9, 10, 11)}
        composite = {}
        for name, months in seasons.items():
            vals = [anom[k] / clim[k[1]] * 100 for k in anom if k[1] in months and nino_map.get(k, 0) >= strong]
            composite[name] = {"months": len(vals), "rain_change_pct": round(statistics.mean(vals), 1) if vals else None}
        stats[city] = {"corr_by_lag_months": lagged, "strong_nino_rain_change_by_season": composite,
                       "climatology_mm": {m: round(v, 1) for m, v in sorted(clim.items())}}
    return stats


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf-8")


def cmd_enso_sierra(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    nino = parse_nino(_get(NINO_URL))
    rains = {}
    end = datetime.now(timezone.utc).year
    for city, (lat, lon) in SIERRA.items():
        rains[city] = parse_power(json.loads(_get(POWER_URL.format(lat=lat, lon=lon, end=end))))
    with open(out / "nino34.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "nino34_anom"])
        for y, m, a in nino:
            w.writerow([f"{y}-{m:02d}-01", a])
    for city, rain in rains.items():
        with open(out / f"lluvia_{city.lower()}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["fecha", "lluvia_mm"])
            for (y, m) in sorted(rain):
                w.writerow([f"{y}-{m:02d}-01", round(rain[(y, m)], 1)])
    stats = enso_sierra_stats(nino, rains)
    summary = {"nino_last": nino[-6:], "rain_last": {c: sorted(r.items())[-3:] for c, r in rains.items()}, "stats": stats}
    (out / "stats.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, default=str))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pendientes")
    e = sub.add_parser("enso-sierra")
    e.add_argument("--out", default=str(DATA / "work" / "enso"))
    g = sub.add_parser("guardar")
    g.add_argument("archivo")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.cmd == "pendientes":
        print(json.dumps([r for r in load_all()["requests"] if r["status"] == "pendiente"], ensure_ascii=False, indent=1))
    elif args.cmd == "enso-sierra":
        cmd_enso_sierra(args.out)
    else:
        print(save_result(json.loads(Path(args.archivo).read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
