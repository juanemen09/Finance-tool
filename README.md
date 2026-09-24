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
| `docs/plans/strategy-pipeline.md` | Protocolo del pipeline de estrategias. |
| `tests/` | Pruebas unitarias (Python) y de comportamiento del esquema (SQL). |

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
