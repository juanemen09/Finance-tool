"""Pronóstico diario de TimesFM 3.0 para los 5 pares (papel, investigación personal no comercial).

Corre con el Python del entorno de TimesFM, que tiene PyTorch y los pesos:
  C:\\TimesFM_Research\\.venv\\Scripts\\python.exe -m tools.tsfm_forecast --out data/raw/tsfm
Escribe data/raw/tsfm/<fecha del cierre>.json; si ya existe, no vuelve a cargar el modelo. La inserción y la
puntuación las hace tools.tsfm_ingest con el Python del laboratorio.
"""
import argparse
import ctypes
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ai_trading_lab.candles import closed_only, fetch_klines
from ai_trading_lab.forecasting import HORIZONS, QUANTILES, forecast_rows

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT")
CONTEXT_DAYS = 1000
MIN_FREE_GB = 4.5  # medido con el laboratorio el 2026-09-29: con 3,9 GB la carga se cayó y con 4,9 funcionó


def free_commit_gb():
    if sys.platform != "win32":
        return None

    class M(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong),
                    ("ap", ctypes.c_ulonglong), ("tf", ctypes.c_ulonglong), ("af", ctypes.c_ulonglong),
                    ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]

    m = M()
    m.l = ctypes.sizeof(M)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.af / 1024 ** 3


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data/raw/tsfm")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    series = {}
    for s in SYMBOLS:
        candles = closed_only(fetch_klines(s, "1d", limit=CONTEXT_DAYS))
        series[s] = candles
    origin = min(c[-1].close_time for c in series.values()) + 1  # cierre diario común (00:00 UTC)
    stamp = datetime.fromtimestamp(origin / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    out = Path(args.out) / f"{stamp}.json"
    if out.exists():
        print(json.dumps({"skipped": str(out), "reason": "ya existe el pronóstico de este cierre"}))
        return 0

    free = free_commit_gb()
    if free is not None and free < MIN_FREE_GB:
        print(json.dumps({"error": f"memoria libre {free:.1f} GB < {MIN_FREE_GB} GB; se reintentará más tarde"}))
        return 2

    import torch
    from timesfm3 import ModelConfig, TimesFM3Forecaster
    model = TimesFM3Forecaster(config=ModelConfig(device="cuda" if torch.cuda.is_available() else "cpu",
                                                  quantiles=list(QUANTILES)))
    rows = []
    for s, candles in series.items():
        candles = [c for c in candles if c.close_time < origin]
        closes = np.array([c.close for c in candles], dtype=float)
        out_s = model.predict(context=np.log(closes).astype(np.float32), horizon=max(HORIZONS), return_quantiles=True)
        rows += forecast_rows(s, origin, closes, np.asarray(out_s.quantiles)[:max(HORIZONS)].tolist())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"origin_close_time": stamp, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps({"written": str(out), "rows": len(rows)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
