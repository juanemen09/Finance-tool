# AI Trading Lab

Experimento para saber si un análisis disciplinado asistido por IA, con gestión de riesgo estricta y un
diario sistemático, produce expectativa positiva ajustada al riesgo en Binance Spot (~20 USDT).

El protocolo entre agentes está en [AGENTS.md](AGENTS.md).

## Estructura

| Ruta | Contenido |
|---|---|
| `supabase/migrations/` | Esquema del diario compartido: append-only, RLS activado, sin acceso público. |
| `supabase/seed/` | Estado inicial: agentes, límites de riesgo, eventos abiertos y Trade #001. |
| `ai_trading_lab/` | Velas públicas de Binance, indicadores y puntuación de decisiones. |
| `tools/market_scan.py` | Foto del universo en 1h y 4h con velas cerradas. |
| `tools/score_decisions.py` | Puntúa decisiones del diario con el precio posterior. |
| `ai_trading_lab/backtest.py` | Motor de backtest de una posición: entrada en la apertura siguiente, costes, stop antes que target. |
| `ai_trading_lab/validation.py` | Hard testing: walk-forward, bootstrap, Monte Carlo, entradas aleatorias, meseta, Deflated Sharpe. |
| `ai_trading_lab/strategies.py` | Catálogo de familias de estrategias formalizadas y sus rejillas pre-registrables. |
| `ai_trading_lab/data_store.py` | Histórico oficial de Binance (`data.binance.vision`) verificado por SHA-256, en `data/raw/`. |
| `tools/ingest_sources.py` | Papers recientes de arXiv (q-fin) para clasificar. |
| `tools/run_hard_test.py` | Ejecuta un pre-registro y devuelve la fila de `backtest_runs`. |
| `tools/strategy_signals.py` | Señal actual de las estrategias en papel o validadas. |
| `ai_trading_lab/sentiment.py` | Sentimiento: parseo de Fear & Greed, funding, largo/corto, RSS y Bluesky; tono con VADER + léxico cripto. |
| `tools/ingest_sentiment.py` | Recolector horario de sentimiento y titulares; genera el SQL de inserción. |
| `dashboard/` | Centro de mando local: servidor de solo lectura en 127.0.0.1 y la interfaz. |
| `docs/plans/strategy-pipeline.md` | Protocolo del pipeline de estrategias. |
| `tests/` | Pruebas unitarias (Python) y de comportamiento del esquema (SQL). |

## Centro de mando (local, solo lectura)

Panel personal en `http://127.0.0.1:8765`: cuenta, gráfico de velas con el canal de S-CHANNEL-1D, Claude frente a
Codex, propuesta activa con sus condiciones, radar de rupturas, línea de tiempo, estrategias, sentimiento, titulares e
investigación. Solo escucha en tu PC y usa un rol de base de datos que no puede escribir nada.

Configuración (una vez):

1. En Supabase → SQL Editor, dale contraseña al rol de solo lectura (elígela tú; usa solo letras y números, larga):
   `alter role dashboard_reader with login password 'TU_CONTRASEÑA';`
2. En Supabase → **Connect** → **Session pooler**, copia el host (algo como `aws-…-us-east-2.pooler.supabase.com`).
3. En el archivo `.env` de esta carpeta (git lo ignora) añade una línea:
   `DASHBOARD_DATABASE_URL=postgresql://dashboard_reader.arxdfgphjybdxgdpqmkh:TU_CONTRASEÑA@HOST:5432/postgres`
4. `pip install -r requirements.txt` y luego `python -m dashboard` (abre el navegador solo).

La contraseña nunca se escribe en el chat ni en el repositorio.

### Ingesta directa del recolector (ahorra uso)

El ciclo horario inserta los titulares con un rol que solo puede **añadir** filas en `news_items` y
`sentiment_observations` (no lee ni modifica nada más):

1. En el SQL Editor: `alter role lab_ingest with login password 'OTRA_CONTRASEÑA';` (distinta de la del panel).
2. En `.env`: `INGEST_DATABASE_URL=postgresql://lab_ingest.arxdfgphjybdxgdpqmkh:OTRA_CONTRASEÑA@aws-0-us-east-2.pooler.supabase.com:5432/postgres`

Sin esa línea, el recolector sigue funcionando en el modo anterior (genera el SQL para que lo ejecute el agente).

## Pruebas

```bash
python -m unittest discover -s tests -t .
```

Esquema (Postgres 17 en Docker; todo corre dentro de una transacción que se revierte):

```bash
docker run -d --name atl-pg-test -e POSTGRES_PASSWORD=test postgres:17
docker exec atl-pg-test psql -U postgres -c "create role anon nologin; create role authenticated nologin;"
docker exec -i atl-pg-test psql -U postgres -v ON_ERROR_STOP=1 < supabase/migrations/20260923230000_shared_journal.sql
docker exec -i atl-pg-test psql -U postgres -v ON_ERROR_STOP=1 < tests/sql/journal_test.sql
```
