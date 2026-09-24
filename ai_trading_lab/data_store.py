"""Histórico de velas desde los archivos oficiales de Binance (data.binance.vision), verificados por SHA-256.

Los meses cerrados salen de ZIP mensuales con checksum publicado; el mes en curso, de la API pública.
Todo se cachea en data/raw/ (fuera de git). El hash del conjunto identifica exactamente los datos usados
en cada backtest.
"""
import csv
import hashlib
import io
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from ai_trading_lab.backtest import Bars
from ai_trading_lab.candles import fetch_klines

VISION = "https://data.binance.vision/data/spot/monthly/klines"
ROOT = Path(__file__).resolve().parent.parent / "data" / "raw"


class ChecksumMismatch(Exception):
    pass


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _month_file(symbol, interval, year, month):
    name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
    path = ROOT / symbol / interval / name
    missing = path.with_suffix(".missing")
    if path.exists():
        return path
    if missing.exists():
        return None
    try:
        payload = _get(f"{VISION}/{symbol}/{interval}/{name}")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            # El activo aún no cotizaba: un mes cerrado que no existe no aparecerá después.
            missing.parent.mkdir(parents=True, exist_ok=True)
            missing.touch()
            return None
        raise
    expected = _get(f"{VISION}/{symbol}/{interval}/{name}.CHECKSUM").decode().split()[0]
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ChecksumMismatch(f"{name}: esperado {expected}, obtenido {actual}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _rows_from_zip(path):
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            for row in csv.reader(io.TextIOWrapper(handle)):
                if not row or not row[0].isdigit():
                    continue  # cabecera
                open_time = int(row[0])
                if open_time > 10**14:  # desde 2025 los ZIP de spot vienen en microsegundos
                    open_time //= 1000
                yield open_time, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])


def _months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


HOUR_MS = 3_600_000
HOURS_PER_INTERVAL = {"1h": 1, "4h": 4, "1d": 24}


def resample(bars, hours):
    """Agrupa velas de 1h en bloques alineados a UTC (00:00, 04:00, ... como Binance). El último bloque se
    descarta si aún no cerró; un bloque con huecos de mantenimiento se conserva con las horas que tenga."""
    if hours == 1:
        return bars
    bucket_ms = hours * HOUR_MS
    keys = bars.open_time // bucket_ms
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:], len(bars)]
    open_time = keys[starts] * bucket_ms
    last_complete = bars.open_time[-1] + HOUR_MS >= open_time[-1] + bucket_ms
    first = 0 if bars.open_time[0] == open_time[0] else 1  # el bloque inicial empezado a medias no es una vela real
    n = len(starts) if last_complete else len(starts) - 1
    return Bars(
        open_time[first:n],
        bars.open[starts][first:n],
        np.maximum.reduceat(bars.high, starts)[first:n],
        np.minimum.reduceat(bars.low, starts)[first:n],
        bars.close[ends - 1][first:n],
        np.add.reduceat(bars.volume, starts)[first:n],
    )


def load(symbol, interval="1h", since=date(2017, 8, 1), now=None):
    """Velas cerradas de `since` hasta ahora. Devuelve (Bars, data_hash).

    4h y 1d se construyen desde las velas de 1h verificadas: un solo origen de datos para todas las temporalidades.
    """
    if interval != "1h":
        hourly, hourly_hash = load(symbol, "1h", since, now)
        digest = hashlib.sha256(f"{hourly_hash}:{interval}".encode()).hexdigest()
        return resample(hourly, HOURS_PER_INTERVAL[interval]), digest
    now = now or datetime.now(timezone.utc)
    last_full_month = date(now.year, now.month, 1)
    rows, digests = {}, []
    for y, m in _months(since, last_full_month):
        if (y, m) == (now.year, now.month):
            break
        path = _month_file(symbol, interval, y, m)
        if path is None:
            continue
        digests.append(f"{path.name}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
        for r in _rows_from_zip(path):
            rows[r[0]] = r

    # Mes en curso: API pública, solo velas cerradas.
    start_ms = int(datetime(now.year, now.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    now_ms = int(now.timestamp() * 1000)
    api_rows = []
    while True:
        batch = fetch_klines(symbol, interval, limit=1000, start_ms=start_ms)
        closed = [c for c in batch if c.close_time <= now_ms]
        for c in closed:
            rows[c.open_time] = (c.open_time, c.open, c.high, c.low, c.close, c.volume)
            api_rows.append(rows[c.open_time])
        if len(batch) < 1000 or not closed:
            break
        start_ms = closed[-1].open_time + 1
    # El hash describe el contenido, no la hora de la consulta: mismas velas, mismo hash.
    digests.append(f"api:{symbol}:{interval}:{hashlib.sha256(repr(sorted(set(api_rows))).encode()).hexdigest()}")

    a = np.array([rows[k] for k in sorted(rows)], float)
    bars = Bars(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])
    return bars, hashlib.sha256("\n".join(digests).encode()).hexdigest()
