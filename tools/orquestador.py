"""Orquestador horario: prepara en Obsidian la nota de la hora antes de que decidan Claude y Codex.

  C:\\Python314\\pythonw.exe tools\\orquestador.py        (tarea «AI Trading Lab\\Orquestador», minuto 01 de cada hora)
  python -m tools.orquestador --dry-run                 (calcula todo e imprime la nota, sin escribir)
  python -m tools.orquestador guardia BTCUSDT           (guardia de ejecución en vivo; la usa Codex antes de operar)

Plano minuto a minuto en docs/plans/pipeline-horario.md. Resumen de la corrida:
  1. Mercado: indicadores de 1h de los 5 pares (Binance, API pública).
  2. Guardia de ejecución: spread y deslizamiento estimado de una orden de 45 USDT (el tope vigente) desde el libro de órdenes;
     marca `abortar` si el spread > 0,2 % o el deslizamiento > 0,15 % (regla que aplica Codex, AGENTS.md).
  3. Sentimiento: Fear & Greed y tono de titulares del diario (rol dashboard_reader).
  4. TimesFM 1-4 h: proceso efímero con su propio Python; al terminar libera toda su memoria.
  5. Etapas opcionales de config/orquestador.json: FinBERT puntúa los titulares como proceso efímero con su propio
     Python (un contenedor haría crecer la máquina virtual de Docker, que no devuelve la memoria a Windows); las de
     tipo imagen corren con `docker run --rm` y límite de memoria.
  6. Memoria semántica: las horas pasadas más parecidas quedan enlazadas como patrones.
  7. Nota de la hora por la Local REST API de Obsidian (si Obsidian está cerrado, se escribe el archivo), y se
     completan las horas previas con la tesis de cada agente y su resultado (#tesis-exitosa, #tesis-fallida, #anomalia).
Todo es contexto en papel: nada de aquí propone, aprueba ni ejecuta operaciones.
"""
import argparse
import gc
import json
import math
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pythonw lo lanza como script, sin -m
    sys.path.insert(0, str(ROOT))

from dashboard.config import load_env  # noqa: E402
from tools.obsidian_sync import END, FOLDER, START, safe_name  # noqa: E402

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ONDOUSDT")
ORDER_USDT = 45.0  # tope por posición desde el 2026-10-06
MAX_SPREAD_PCT = 0.2
MAX_SLIPPAGE_PCT = 0.15
TSFM_PYTHON = Path(r"C:\TimesFM_Research\.venv\Scripts\python.exe")
MIN_FREE_GB = 4.5
DEADLINE_SECONDS = 170          # la nota debe estar lista antes de que arranque el ciclo de Claude
REVISIT_HOURS = 8               # horas previas que se completan en cada corrida
OUT = ROOT / "data" / "raw" / "horas"
MEMORY = OUT / "memoria.jsonl"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEPTH_URL = "https://api.binance.com/api/v3/depth?symbol={s}&limit=100"


def log(line):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "log.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ} {line}\n")


def note_name(hour):
    """Nombre de la nota de una vela de 1h por su hora UTC de cierre: 2026-09-30_17H00."""
    return f"{hour:%Y-%m-%d}_{hour:%H}H00"


# ---------------------------------------------------------------- 1. indicadores
def ema(values, n):
    k, out = 2 / (n + 1), values[0]
    for v in values[1:]:
        out = v * k + out * (1 - k)
    return out


def rsi(closes, n=14):
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains, losses = gains + max(d, 0), losses + max(-d, 0)
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def indicators(candles):
    closes = [c.close for c in candles]
    tr = [max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)) for p, c in zip(candles[:-1], candles[1:])]
    vol = [c.volume for c in candles]
    price = closes[-1]
    e20, e50 = ema(closes[-120:], 20), ema(closes[-150:], 50)
    return {"precio": price, "ret_1h_pct": (price / closes[-2] - 1) * 100, "ret_24h_pct": (price / closes[-25] - 1) * 100,
            "rsi14": rsi(closes), "ema20": e20, "ema50": e50, "sobre_ema50": price > e50,
            "atr_pct": sum(tr[-14:]) / 14 / price * 100, "volumen_relativo": vol[-1] / (sum(vol[-25:-1]) / 24 or 1)}


# ---------------------------------------------------------------- 2. guardia de ejecución
def _walk(levels, notional_usdt):
    """Precio medio al llenar `notional_usdt` recorriendo el libro; None si no alcanza la profundidad."""
    left, cost, qty = notional_usdt, 0.0, 0.0
    for price, amount in ((float(p), float(q)) for p, q in levels):
        take = min(left, price * amount)
        cost, qty, left = cost + take, qty + take / price, left - take
        if left <= 1e-12:
            return cost / qty
    return None


def execution_guard(book, notional=ORDER_USDT):
    bids, asks = book.get("bids") or [], book.get("asks") or []
    if not bids or not asks:
        return {"abortar": True, "motivo": "libro de órdenes vacío"}
    bid, ask = float(bids[0][0]), float(asks[0][0])
    mid = (bid + ask) / 2
    spread = (ask - bid) / mid * 100
    buy, sell = _walk(asks, notional), _walk(bids, notional)
    slip_buy = None if buy is None else (buy / ask - 1) * 100
    slip_sell = None if sell is None else (1 - sell / bid) * 100
    reasons = []
    if spread > MAX_SPREAD_PCT:
        reasons.append(f"spread {spread:.3f} % > {MAX_SPREAD_PCT} %")
    for side, slip in (("compra", slip_buy), ("venta", slip_sell)):
        if slip is None:
            reasons.append(f"profundidad insuficiente para la {side}")
        elif slip > MAX_SLIPPAGE_PCT:
            reasons.append(f"deslizamiento de {side} {slip:.3f} % > {MAX_SLIPPAGE_PCT} %")
    return {"bid": bid, "ask": ask, "spread_pct": spread, "deslizamiento_compra_pct": slip_buy,
            "deslizamiento_venta_pct": slip_sell, "orden_usdt": notional, "abortar": bool(reasons),
            "motivo": "; ".join(reasons) or "dentro de los límites"}


def fetch_book(symbol):
    req = urllib.request.Request(DEPTH_URL.format(s=symbol), headers={"User-Agent": "ai-trading-lab/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


# ---------------------------------------------------------------- 6. memoria semántica (horas parecidas)
FEATURES = ("btc_ret_24h_pct", "btc_rsi14", "btc_atr_pct", "fear_greed", "tono_mercado")


def feature_vector(record):
    btc = record.get("mercado", {}).get("BTCUSDT", {})
    s = record.get("sentimiento", {})
    vals = [btc.get("ret_24h_pct"), btc.get("rsi14"), btc.get("atr_pct"), s.get("fear_greed"), s.get("tono_mercado")]
    return [None if v is None else float(v) for v in vals]


def similar_hours(history, current, k=2, min_gap_hours=24):
    """Las k horas pasadas cuyo régimen (retorno y RSI de BTC, volatilidad, Fear & Greed, tono) más se parece al de
    ahora, con distancia euclídea sobre valores normalizados. Se excluyen las últimas 24 h: serían «parecidas» solo
    por ser vecinas."""
    now = datetime.fromisoformat(current["hora"])
    pool = [h for h in history if now - datetime.fromisoformat(h["hora"]) >= timedelta(hours=min_gap_hours)]
    cur = feature_vector(current)
    if len(pool) < 3:
        return []
    dims = [i for i in range(len(FEATURES)) if cur[i] is not None]
    stats = {}
    for i in dims:
        vals = [feature_vector(h)[i] for h in pool if feature_vector(h)[i] is not None]
        if len(vals) >= 3:
            mean = sum(vals) / len(vals)
            stats[i] = (mean, math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) or 1.0)
    scored = []
    for h in pool:
        fv = feature_vector(h)
        used = [i for i in stats if fv[i] is not None]
        if len(used) < 2:
            continue
        d = math.sqrt(sum(((fv[i] - cur[i]) / stats[i][1]) ** 2 for i in used) / len(used))
        scored.append((d, h["nombre"]))
    return [{"nombre": n, "distancia": round(d, 3)} for d, n in sorted(scored)[:k]]


# ---------------------------------------------------------------- 7. resultado de horas pasadas
def evaluate(record, later):
    """Etiquetas de resultado cuando ya pasaron 4 h: #anomalia si algún cierre real quedó fuera de la banda p10-p90 de
    TimesFM a 4 h; #tesis-exitosa / #tesis-fallida si Claude propuso comprar o vender y el precio fue en esa dirección."""
    tags, detail = [], {}
    if not later:
        return {"resultado": "pendiente", "tags": [], "detalle": {}}
    for s, fc in (record.get("timesfm") or {}).items():
        step = next((x for x in fc.get("steps", []) if x["h"] == 4), None)
        real = later.get("mercado", {}).get(s, {}).get("precio")
        if step and real is not None:
            outside = not (step["p10"] <= real <= step["p90"])
            detail[s] = {"real_4h": real, "p10": step["p10"], "p90": step["p90"], "fuera_de_banda": outside}
            if outside and "anomalia" not in tags:
                tags.append("anomalia")
    thesis = (record.get("agentes") or {}).get("claude") or {}
    action, sym = thesis.get("accion"), thesis.get("simbolo")
    resultado = "sin-tesis-direccional"
    if action in ("BUY_CANDIDATE", "SELL_CANDIDATE") and sym:
        start = record.get("mercado", {}).get(sym, {}).get("precio")
        end = later.get("mercado", {}).get(sym, {}).get("precio")
        if start and end:
            right = (end > start) == (action == "BUY_CANDIDATE")
            resultado = "exitosa" if right else "fallida"
            tags.append("tesis-exitosa" if right else "tesis-fallida")
    return {"resultado": resultado, "tags": tags, "detalle": detail}


# ---------------------------------------------------------------- nota de la hora
def _yaml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return "null" if (isinstance(v, float) and not math.isfinite(v)) else (str(round(v, 6)) if isinstance(v, float) else str(v))
    if v is None:
        return "null"
    if isinstance(v, list):
        return "[" + ", ".join(_yaml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)  # cadena entre comillas: YAML válido siempre


def frontmatter(record, outcome):
    """YAML tipado para Dataview: números como número, fechas ISO, listas de etiquetas. Un campo por activo y métrica
    (btc_precio, btc_p10_4h, ...) para que las consultas no dependan de objetos anidados."""
    fm = {"tipo": "hora", "hora_utc": record["hora"], "ciclo": record["ciclo"], "fuente": "ai-trading-lab",
          "fear_greed": record.get("sentimiento", {}).get("fear_greed"),
          "sentimiento_mercado": record.get("sentimiento", {}).get("tono_mercado"),
          "sentimiento_finbert": record.get("sentimiento", {}).get("finbert"),
          "tesis_claude": (record.get("agentes") or {}).get("claude", {}).get("accion"),
          "tesis_codex": (record.get("agentes") or {}).get("chatgpt", {}).get("accion"),
          "resultado": outcome["resultado"], "guardia_abortar": any(g.get("abortar") for g in (record.get("guardia") or {}).values())}
    for s in SYMBOLS:
        k = s.replace("USDT", "").lower()
        m = record.get("mercado", {}).get(s, {})
        fm[f"{k}_precio"] = m.get("precio")
        fm[f"{k}_rsi14"] = m.get("rsi14")
        step4 = next((x for x in (record.get("timesfm") or {}).get(s, {}).get("steps", []) if x["h"] == 4), {})
        fm[f"{k}_p10_4h"], fm[f"{k}_p50_4h"], fm[f"{k}_p90_4h"] = step4.get("p10"), step4.get("p50"), step4.get("p90")
        fm[f"{k}_spread_pct"] = (record.get("guardia") or {}).get(s, {}).get("spread_pct")
    fm["tags"] = ["hora", *outcome["tags"]]
    return "---\n" + "\n".join(f"{k}: {_yaml_value(v)}" for k, v in fm.items()) + "\n---\n"


def _fmt(v, d=2):
    return "—" if v is None else f"{v:,.{d}f}".replace(",", " ")


def note_body(record, prev_name, similar, outcome):
    name = record["nombre"]
    quito = (datetime.fromisoformat(record["hora"]) - timedelta(hours=5)).strftime("%H:%M")
    links = [f"[[AI Trading Lab]]", f"anterior: [[{prev_name}]]" if prev_name else None]
    lines = [f"# Hora {name} (UTC) · {quito} en Quito", " · ".join(x for x in links if x),
             ("Patrones parecidos: " + ", ".join(f"[[{s['nombre']}]] (distancia {s['distancia']})" for s in similar)) if similar else
             "Patrones parecidos: todavía no hay suficiente memoria.", "",
             "## Mercado (velas de 1 h)", "| Activo | Precio | 1 h | 24 h | RSI 14 | Sobre EMA50 | ATR % | Vol. rel. |", "|---|---|---|---|---|---|---|---|"]
    for s in SYMBOLS:
        m = record.get("mercado", {}).get(s)
        if m:
            above = m.get("sobre_ema50")
            lines.append(f"| [[{s.replace('USDT', '')}]] | {_fmt(m.get('precio'), 4)} | {_fmt(m.get('ret_1h_pct'))} % | {_fmt(m.get('ret_24h_pct'))} % | "
                         f"{_fmt(m.get('rsi14'), 1)} | {'—' if above is None else 'sí' if above else 'no'} | {_fmt(m.get('atr_pct'))} | {_fmt(m.get('volumen_relativo'))} |")
    lines += ["", "## Oráculo [[TimesFM]] a 4 h (papel, no señal)"]
    tf = record.get("timesfm") or {}
    if tf:
        lines += ["| Activo | p10 | p50 | p90 |", "|---|---|---|---|"]
        for s, fc in tf.items():
            st = next((x for x in fc["steps"] if x["h"] == 4), None)
            if st:
                lines.append(f"| [[{s.replace('USDT', '')}]] | {_fmt(st['p10'], 4)} | {_fmt(st['p50'], 4)} | {_fmt(st['p90'], 4)} |")
    else:
        lines.append(f"Sin pronóstico esta hora: {record.get('timesfm_error') or 'no corrió'}.")
    lines += ["", "## Guardia de ejecución (orden de 45 USDT; Codex la recalcula en vivo antes de operar)",
              "| Activo | Spread % | Desliz. compra % | Desliz. venta % | ¿Abortar? |", "|---|---|---|---|---|"]
    for s, g in (record.get("guardia") or {}).items():
        lines.append(f"| {s.replace('USDT', '')} | {_fmt(g.get('spread_pct'), 3)} | {_fmt(g.get('deslizamiento_compra_pct'), 3)} | "
                     f"{_fmt(g.get('deslizamiento_venta_pct'), 3)} | {'SÍ: ' + g['motivo'] if g.get('abortar') else 'no'} |")
    sent = record.get("sentimiento") or {}
    lines += ["", "## [[Sentimiento]]", f"Fear & Greed {_fmt(sent.get('fear_greed'), 0)} · tono de titulares 24 h {_fmt(sent.get('tono_mercado'))} "
              f"({sent.get('modelo', 'VADER')})."]
    fb = (record.get("contenedores") or {}).get("finbert") or {}
    if fb.get("n"):
        per = ", ".join(f"{k.replace('USDT', '')} {_fmt(v['tono'])}" for k, v in fb.get("por_activo", {}).items())
        lines.append(f"FinBERT sobre {fb['n']} titulares: {_fmt(fb.get('mercado'))} ({fb.get('positivos', 0)} positivos, "
                     f"{fb.get('negativos', 0)} negativos){' · ' + per if per else ''}.")
        for key, label in (("mas_negativo", "Más negativo"), ("mas_positivo", "Más positivo")):
            for x in fb.get(key) or []:
                lines.append(f"- {label} ({_fmt(x['tono'])}): {x['titulo']}")
    elif fb.get("error"):
        lines.append(f"FinBERT no corrió: {fb['error']}.")
    ag = record.get("agentes") or {}
    lines += ["", "## Tesis de los agentes"]
    if ag:
        for key, label in (("claude", "Claude"), ("chatgpt", "Codex")):
            a = ag.get(key)
            lines.append(f"- [[{label}]]: {a['accion']} {a.get('simbolo') or ''} — {a.get('regimen', '')[:400]}" if a else f"- [[{label}]]: sin análisis de este ciclo.")
    else:
        lines.append("Se completa en la corrida siguiente, cuando Claude (minuto 05) y Codex (minuto 15) ya escribieron.")
    lines += ["", "## Resultado", f"{outcome['resultado']} · etiquetas: {', '.join('#' + t for t in outcome['tags']) or '—'}", "",
              "```json", json.dumps({"datos_modelos": {k: record.get(k) for k in ("timesfm", "guardia", "sentimiento", "contenedores")},
                                     "evaluacion_4h": outcome["detalle"]}, ensure_ascii=False, indent=1, default=str), "```"]
    return "\n".join(lines)


def render(record, prev_name, similar, outcome, existing=None):
    """Frontmatter (siempre regenerado) + bloque generado; el texto del usuario fuera del bloque se conserva."""
    block = f"{START}\n{note_body(record, prev_name, similar, outcome)}\n{END}"
    head = frontmatter(record, outcome)
    if existing and START in existing and END in existing:
        before, rest = existing.split(START, 1)
        after = rest.split(END, 1)[1]
        before = before.split("---\n", 2)[2] if before.startswith("---\n") and before.count("---\n") >= 2 else before
        return head + before + block + after
    return head + block + "\n"


# ---------------------------------------------------------------- Obsidian: Local REST API con respaldo a archivo
class Obsidian:
    """Lee y escribe notas por la Local REST API (HTTPS en 127.0.0.1:27124). El certificado del plugin es propio: se
    descarga una vez de la propia API local y se fija como única autoridad válida. Si Obsidian está cerrado o falta la
    clave, escribe directo en el archivo de la bóveda (misma nota, mismo resultado)."""

    def __init__(self, vault, url, key):
        self.vault, self.url, self.key = Path(vault), url.rstrip("/"), key
        self.ctx, self.api_ok = None, bool(key)

    def _context(self):
        if self.ctx is None:
            cert = OUT / "obsidian-rest.crt"
            if not cert.exists():
                raw = ssl.create_default_context()
                raw.check_hostname, raw.verify_mode = False, ssl.CERT_NONE  # solo 127.0.0.1, para bajar su certificado
                with urllib.request.urlopen(f"{self.url}/obsidian-local-rest-api.crt", context=raw, timeout=5) as r:
                    OUT.mkdir(parents=True, exist_ok=True)
                    cert.write_bytes(r.read())
            self.ctx = ssl.create_default_context(cafile=str(cert))
            self.ctx.check_hostname = False  # el certificado del plugin no nombra 127.0.0.1; se valida por la firma fijada
        return self.ctx

    def _request(self, method, path, body=None):
        url = f"{self.url}/vault/{urllib.parse.quote(path)}"
        req = urllib.request.Request(url, data=body, method=method, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "text/markdown; charset=utf-8"})
        with urllib.request.urlopen(req, context=self._context(), timeout=10) as r:
            return r.read().decode("utf-8")

    def read(self, rel):
        path = f"{FOLDER}/{rel}"
        if self.api_ok:
            try:
                return self._request("GET", path)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                self.api_ok = False
            except (OSError, ssl.SSLError):
                self.api_ok = False
        f = self.vault / FOLDER / rel
        return f.read_text(encoding="utf-8") if f.exists() else None

    def write(self, rel, text):
        path = f"{FOLDER}/{rel}"
        if self.api_ok:
            try:
                self._request("PUT", path, text.encode("utf-8"))
                return "api"
            except (OSError, ssl.SSLError):
                self.api_ok = False
        f = (self.vault / FOLDER / rel).resolve()
        if (self.vault / FOLDER).resolve() not in f.parents:
            raise ValueError("ruta fuera de la carpeta del laboratorio")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        return "archivo"


# ---------------------------------------------------------------- etapas con E/S
def stage_market():
    from ai_trading_lab.candles import closed_only, fetch_klines
    out = {}
    for s in SYMBOLS:
        out[s] = indicators(closed_only(fetch_klines(s, "1h", limit=200)))
    return out


def stage_guard():
    return {s: execution_guard(fetch_book(s)) for s in SYMBOLS}


def free_gb():
    from tools.tsfm_forecast import free_commit_gb
    return free_commit_gb()


def stage_timesfm(budget):
    from tools import tsfm_client
    if tsfm_client.ready():  # servicio residente: el modelo ya está cargado, no hace falta memoria nueva
        from tools.tsfm_hourly import forecast_all
        try:
            return forecast_all(tsfm_client.predict_quantiles), None
        except Exception as error:  # si el servicio cae a mitad, se intenta el proceso efímero
            log(f"servicio de TimesFM: {type(error).__name__}")
        finally:
            gc.collect()
    free = free_gb()
    if free is not None and free < MIN_FREE_GB:
        return None, f"memoria libre {free:.1f} GB < {MIN_FREE_GB} GB"
    if not TSFM_PYTHON.exists():
        return None, "no está el entorno de TimesFM"
    try:
        r = subprocess.run([str(TSFM_PYTHON), "-m", "tools.tsfm_hourly"], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", timeout=max(20, budget), creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return None, "TimesFM no terminó a tiempo"
    finally:
        gc.collect()  # el modelo vivió en otro proceso, ya cerrado; aquí solo se limpian los objetos del padre
    if r.returncode != 0:
        return None, f"TimesFM falló (código {r.returncode})"
    return json.loads(r.stdout.strip().splitlines()[-1]), None


def _last_json(r, name):
    if r.returncode != 0:
        last = (r.stderr or "").strip().splitlines()[-1:] or [""]
        raise RuntimeError(f"{name}: código {r.returncode} {last[0][-160:]}".strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


def run_container(image, args, memory="2g", timeout=120, run=subprocess.run, payload=""):
    """Contenedor efímero: `--rm` lo destruye al terminar y `--memory` le pone techo. El contexto entra por la
    entrada estándar (la línea de comandos de Windows se queda corta con 200 titulares). Devuelve el JSON que imprime."""
    cmd = ["docker", "run", "--rm", "--memory", memory, "--cpus", "2", "--network", "none", "-i", image, *args]
    r = run(cmd, input=payload, capture_output=True, text=True, encoding="utf-8", timeout=timeout, creationflags=NO_WINDOW)
    return _last_json(r, image)


def run_process(python, module, payload, timeout=120, run=subprocess.run):
    """Proceso efímero con otro Python: carga su modelo, imprime un JSON y muere; Windows recupera toda su memoria."""
    r = run([python, "-m", module], input=payload, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            timeout=timeout, creationflags=NO_WINDOW)
    return _last_json(r, module)


def stage_containers(config, context, budget, run=subprocess.run, free=None):
    """Etapas opcionales (FinBERT, visión...). Solo corren las marcadas `activo` en config/orquestador.json, con su
    modelo o imagen ya en esta PC (el orquestador nunca descarga nada) y si queda la memoria que piden."""
    out = {}
    for c in config.get("contenedores", []):
        if not c.get("activo") or budget() < 30:
            continue
        need = c.get("memoria_min_gb")
        left = (free or free_gb)() if need else None
        if left is not None and left < need:
            out[c["nombre"]] = {"error": f"memoria libre {left:.1f} GB < {need} GB"}
            continue
        try:
            payload = json.dumps(context, ensure_ascii=False, default=str)
            timeout = min(c.get("timeout", 90), int(budget()) - 10)
            if c.get("python"):
                python = os.path.expandvars(c["python"])
                if not Path(python).exists():
                    out[c["nombre"]] = {"error": "no está instalado su entorno"}
                    continue
                out[c["nombre"]] = run_process(python, c["modulo"], payload, timeout, run=run)
            else:
                out[c["nombre"]] = run_container(c["imagen"], c.get("args", []), c.get("memoria", "2g"), timeout, run=run, payload=payload)
        except Exception as error:  # una etapa opcional caída no detiene la nota
            out[c["nombre"]] = {"error": f"{type(error).__name__}: {error}"[:220] if isinstance(error, RuntimeError) else type(error).__name__}
        finally:
            gc.collect()
    return out


def stage_journal(url, cycles):
    """Sentimiento vigente y análisis de los agentes de las horas indicadas (solo lectura)."""
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=15) as conn:
        fg = conn.execute("select value from v_sentiment_latest where metric = 'fear_greed' limit 1").fetchone()
        tone = conn.execute("select avg_sentiment from v_news_sentiment_24h where symbol = 'MERCADO'").fetchone()
        rows = conn.execute("select distinct on (agent_id, cycle_id) agent_id, cycle_id, proposed_action, symbol, market_regime "
                            "from analyses where cycle_id = any(%s) order by agent_id, cycle_id, id desc", (cycles,)).fetchall()
        news = conn.execute("select title, symbols from news_items where published_at > now() - interval '24 hours' "
                            "order by published_at desc limit 200").fetchall()
    agents = {}
    for r in rows:
        agents.setdefault(r["cycle_id"], {})[r["agent_id"]] = {"accion": r["proposed_action"], "simbolo": r["symbol"],
                                                               "regimen": r["market_regime"] or ""}
    sentiment = {"fear_greed": float(fg["value"]) if fg else None,
                 "tono_mercado": float(tone["avg_sentiment"]) if tone and tone["avg_sentiment"] is not None else None, "modelo": "VADER"}
    headlines = [{"titulo": n["title"], "simbolos": list(n["symbols"] or [])} for n in news]
    return sentiment, agents, headlines


# ---------------------------------------------------------------- corrida
def load_memory():
    try:
        return [json.loads(line) for line in MEMORY.read_text(encoding="utf-8").splitlines() if line.strip()]
    except FileNotFoundError:
        return []


def save_memory(records):
    OUT.mkdir(parents=True, exist_ok=True)
    MEMORY.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records[-24 * 120:]) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("comando", nargs="?", default="hora", choices=["hora", "guardia"])
    parser.add_argument("simbolo", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    if args.comando == "guardia":
        s = (args.simbolo or "").upper()
        if s not in SYMBOLS:
            print("Uso: python -m tools.orquestador guardia BTCUSDT")
            return 2
        print(json.dumps(execution_guard(fetch_book(s)), ensure_ascii=False, indent=1))
        return 0

    started = time.monotonic()
    budget = lambda: DEADLINE_SECONDS - (time.monotonic() - started)  # noqa: E731
    env = load_env()
    local = json.loads((ROOT / "config" / "workspace.local.json").read_text(encoding="utf-8"))
    try:
        config = json.loads((ROOT / "config" / "orquestador.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    record = {"hora": hour.isoformat(), "nombre": note_name(hour), "ciclo": f"{hour:%Y-%m-%dT%H}Z"}

    for key, fn in (("mercado", stage_market), ("guardia", stage_guard)):
        try:
            record[key] = fn()
        except Exception as error:
            record[key] = {}
            log(f"error en {key}: {type(error).__name__}")
    memory = [r for r in load_memory() if r["nombre"] != record["nombre"]]
    revisit = [r for r in memory if hour - datetime.fromisoformat(r["hora"]) <= timedelta(hours=REVISIT_HOURS)]
    cycles = [record["ciclo"], *[r["ciclo"] for r in revisit]]
    try:
        sentiment, agents, headlines = stage_journal(env.get("DASHBOARD_DATABASE_URL", ""), cycles)
    except Exception as error:
        sentiment, agents, headlines = {}, {}, []
        log(f"error en el diario: {type(error).__name__}")
    record["sentimiento"] = sentiment
    record["timesfm"], record["timesfm_error"] = stage_timesfm(int(budget()) - 40)
    record["contenedores"] = stage_containers(config, {"mercado": record["mercado"], "hora": record["hora"], "titulares": headlines}, budget)
    fb = record["contenedores"].get("finbert") or {}
    if fb.get("mercado") is not None:
        record["sentimiento"]["finbert"] = fb["mercado"]
    record["similares"] = similar_hours(memory, record)

    obsidian = Obsidian(local["obsidian_vault"], env.get("OBSIDIAN_API_URL", "https://127.0.0.1:27124"), env.get("OBSIDIAN_API_KEY", ""))
    by_name = {r["nombre"]: r for r in memory}
    by_name[record["nombre"]] = record
    targets = sorted([*revisit, record], key=lambda r: r["hora"])
    written = []
    for r in targets:
        r["agentes"] = agents.get(r["ciclo"], r.get("agentes") or {})
        h = datetime.fromisoformat(r["hora"])
        later = by_name.get(note_name(h + timedelta(hours=4)))
        outcome = evaluate(r, later)
        prev = note_name(h - timedelta(hours=1))
        prev = prev if prev in by_name else None
        rel = f"Horas/{safe_name(r['nombre'])}.md"
        text = render(r, prev, r.get("similares") or [], outcome, None if args.dry_run else obsidian.read(rel))
        if args.dry_run:
            if r is record:
                print(text)
            continue
        written.append(obsidian.write(rel, text))
        if r is record:  # copia dentro del repo: el ciclo desatendido de Claude no lee fuera de él (evita permisos)
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "actual.md").write_text(text, encoding="utf-8")
    if not args.dry_run:
        save_memory(sorted(by_name.values(), key=lambda r: r["hora"]))
        log(f"{record['nombre']}: {len(written)} nota(s) ({', '.join(sorted(set(written)))}), "
            f"TimesFM {'ok' if record['timesfm'] else record['timesfm_error']}, {DEADLINE_SECONDS - budget():.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
