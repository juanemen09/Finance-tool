"""Cliente del servicio residente de TimesFM (C:\\TimesFM_Research\\laboratorio\\servicio.py, 127.0.0.1:8766).

Con el servicio arriba, pronosticar no carga nada en este proceso: el modelo ya está en memoria allá. Solo la librería
estándar: sirve desde el Python del laboratorio de trading y desde el del entorno de TimesFM.
"""
import json
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8766"
QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def _request(method, path, payload=None, timeout=5, url=URL):
    req = urllib.request.Request(url + path, method=method, data=None if payload is None else json.dumps(payload).encode("utf-8"),
                                 headers={"X-TSFM": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def status(url=URL):
    """{"cargado": ..., "memoria_libre_gb": ..., "error": ...} o None si el servicio no responde."""
    try:
        return _request("GET", "/estado", timeout=3, url=url)
    except (OSError, ValueError):
        return None


def ready(url=URL):
    s = status(url)
    return bool(s and s.get("cargado"))


def predict_quantiles(values, horizon, url=URL):
    """Cuantiles p10..p90 por paso: [[q0.1, ..., q0.9] para cada paso del horizonte]."""
    r = _request("POST", "/pronosticar", {"valores": [float(v) for v in values], "horizonte": int(horizon)}, timeout=300, url=url)
    return [[r["cuantiles"][str(q)][i] for q in QUANTILES] for i in range(int(horizon))]
