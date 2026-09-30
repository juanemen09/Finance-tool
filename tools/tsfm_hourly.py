"""Pronóstico horario de TimesFM 3.0 (1 a 4 horas) para los 5 pares. Papel: contexto de la nota horaria, no señal.

Primero usa el servicio residente de TimesFM (tools.tsfm_client): el modelo ya está cargado y no hace falta memoria
nueva. Si el servicio no responde, se puede correr como proceso efímero con el Python del entorno de TimesFM:
  C:\\TimesFM_Research\\.venv\\Scripts\\python.exe -m tools.tsfm_hourly
que imprime un JSON y termina (al cerrarse, el sistema recupera toda su memoria).
"""
import json
import sys

import numpy as np

from ai_trading_lab.candles import closed_only, fetch_klines
from ai_trading_lab.forecasting import QUANTILES

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT")
CONTEXT_HOURS = 720
HORIZON = 4
PICK = {"p10": QUANTILES.index(0.1), "p50": QUANTILES.index(0.5), "p90": QUANTILES.index(0.9)}


def forecast_all(predict, fetch=fetch_klines):
    """predict(log_closes, horizonte) -> [[cuantiles en log] por paso]. Devuelve precios, no logaritmos."""
    out = {}
    for s in SYMBOLS:
        candles = closed_only(fetch(s, "1h", limit=CONTEXT_HOURS))
        closes = np.array([c.close for c in candles], dtype=float)
        q = np.asarray(predict(np.log(closes), HORIZON))[:HORIZON]
        out[s] = {"last_close": float(closes[-1]), "origin_close_time": candles[-1].close_time + 1,
                  "steps": [{"h": i + 1, **{k: float(np.exp(q[i][j])) for k, j in PICK.items()}} for i in range(HORIZON)]}
    return out


def local_predictor():
    import torch
    from timesfm3 import ModelConfig, TimesFM3Forecaster
    model = TimesFM3Forecaster(config=ModelConfig(device="cuda" if torch.cuda.is_available() else "cpu",
                                                  quantiles=list(QUANTILES)))

    def predict(log_closes, horizon):
        return np.asarray(model.predict(context=np.asarray(log_closes, dtype=np.float32), horizon=horizon,
                                        return_quantiles=True).quantiles)
    return predict


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    from tools import tsfm_client
    predict = tsfm_client.predict_quantiles if tsfm_client.ready() else local_predictor()
    print(json.dumps(forecast_all(predict)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
