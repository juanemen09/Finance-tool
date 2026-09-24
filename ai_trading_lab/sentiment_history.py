"""Historial de sentimiento para el hard testing: Fear & Greed diario y funding de los futuros de Binance.

Funding: archivos mensuales oficiales (data.binance.vision) verificados por SHA-256; el mes en curso, de la API.
Fear & Greed: alternative.me no publica checksums; la primera descarga se congela en data/raw/sentiment/ y su
hash entra en el run, así una prueba se puede repetir con exactamente los mismos datos.

Alineación sin mirar al futuro, para la vela diaria que abre en D y cierra en D+1 00:00 UTC:
  * Fear & Greed: el valor fechado en D (se publica al empezar el día D).
  * Funding: suma de los cobros con hora en [D, D+1): todos ocurren antes del cierre de la vela.
"""
import csv
import hashlib
import io
import json
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone

import numpy as np

from ai_trading_lab.backtest import Bars
from ai_trading_lab.data_store import ROOT as RAW_ROOT, ChecksumMismatch, _months

DAY_MS = 86_400_000
FNG_URL = "https://api.alternative.me/fng/?limit=0&format=json"
FUNDING_VISION = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
FUNDING_API = "https://fapi.binance.com/fapi/v1/fundingRate"
ROOT = RAW_ROOT / "sentiment"
FUNDING_START = date(2019, 9, 1)


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ai-trading-lab/1.0 (research)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def parse_fear_greed_history(payload):
    return {int(row["timestamp"]) * 1000 // DAY_MS * DAY_MS: float(row["value"]) for row in payload["data"]}


def load_fear_greed(refresh=False):
    """{inicio del día UTC en ms: valor}, hash del archivo congelado."""
    path = ROOT / "fear_greed.json"
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(FNG_URL))
    raw = path.read_bytes()
    return parse_fear_greed_history(json.loads(raw)), hashlib.sha256(raw).hexdigest()


def parse_funding_zip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        text = archive.open(archive.namelist()[0]).read().decode()
    return [(int(r[0]), float(r[2])) for r in csv.reader(io.StringIO(text)) if r and r[0].isdigit()]


def _funding_month(symbol, year, month):
    name = f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
    path = ROOT / "funding" / symbol / name
    missing = path.with_suffix(".missing")
    if path.exists():
        return path
    if missing.exists():
        return None
    try:
        payload = _get(f"{FUNDING_VISION}/{symbol}/{name}")
    except urllib.error.HTTPError as error:
        if error.code == 404:  # el contrato aún no existía
            missing.parent.mkdir(parents=True, exist_ok=True)
            missing.touch()
            return None
        raise
    expected = _get(f"{FUNDING_VISION}/{symbol}/{name}.CHECKSUM").decode().split()[0]
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ChecksumMismatch(f"{name}: el checksum no coincide")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def load_funding_events(symbol, now=None):
    """[(hora en ms, tasa)] desde 2019-09 hasta ahora, y un hash del contenido."""
    now = now or datetime.now(timezone.utc)
    events, digests = {}, []
    for y, m in _months(FUNDING_START, date(now.year, now.month, 1)):
        if (y, m) == (now.year, now.month):
            break
        path = _funding_month(symbol, y, m)
        if path is None:
            continue
        raw = path.read_bytes()
        digests.append(f"{path.name}:{hashlib.sha256(raw).hexdigest()}")
        events.update(parse_funding_zip(raw))
    start = int(datetime(now.year, now.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    api = json.loads(_get(f"{FUNDING_API}?symbol={symbol}&startTime={start}&limit=1000"))
    api_events = [(int(r["fundingTime"]), float(r["fundingRate"])) for r in api]
    events.update(api_events)
    digests.append(f"api:{symbol}:{hashlib.sha256(repr(sorted(api_events)).encode()).hexdigest()}")
    return sorted(events.items()), hashlib.sha256("\n".join(digests).encode()).hexdigest()


def daily_funding(events):
    """Suma de los cobros de cada día UTC: comparable entre pares con cobro cada 4h o cada 8h."""
    out = {}
    for t, rate in events:
        day = t // DAY_MS * DAY_MS
        out[day] = out.get(day, 0.0) + rate
    return out


def align_daily(open_time, series):
    """Valor de `series` para el día de apertura de cada vela diaria; nan donde no hay dato."""
    return np.array([series.get(int(t) // DAY_MS * DAY_MS, np.nan) for t in open_time], float)


def attach_daily_features(bars, series_by_name):
    """Velas diarias con las series alineadas, desde el primer día en que existen todas: antes no hay con qué
    comparar la variante y la base. Los huecos posteriores quedan como nan (sin dato, la variante no entra)."""
    aligned = {name: align_daily(bars.open_time, series) for name, series in series_by_name.items()}
    available = np.all([~np.isnan(v) for v in aligned.values()], axis=0)
    if not available.any():
        raise ValueError("las series de sentimiento no cubren ninguna vela")
    start = int(np.argmax(available))
    full = Bars(bars.open_time, bars.open, bars.high, bars.low, bars.close, bars.volume, features=aligned)
    return full.slice(start, len(bars))
