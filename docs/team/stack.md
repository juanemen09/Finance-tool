# Mapa de herramientas (toda la startup)

Generado con `python -m team stack --markdown` desde `config/team/stack.json`. No lo edites a mano.

## Repositorios

| Repo | Visibilidad | Qué es | Stack | Por dónde empezar |
|---|---|---|---|---|
| [Finance-tool (AI Trading Lab)](https://github.com/juanemen09/Finance-tool) | public | Laboratorio de trading asistido por IA en Binance Spot: diario compartido en Supabase, hard testing de estrategias, sentimiento, tesis de infraestructura de IA y centro de mando local. | Python 3.11, PostgreSQL (Supabase), HTML/JS sin framework | README.md, AGENTS.md y docs/team/README.md |
| [PraxiGuard](https://github.com/juanemen09/praxiguard) | private | Producto web para clínicas. Hoy es una demostración con datos ficticios. | TypeScript, Next.js, React, Supabase | README.md y SETUP.md del propio repo (requiere acceso) |
| [Zyneath](https://github.com/juanemen09/Zyneath-Private-Coding) | private | Sistema personal de inteligencia de inversión, en fase 0 y de solo lectura. | Python 3.11 | README.md del propio repo (requiere acceso) |

## Aplicaciones y servicios

| Herramienta | Para qué la usamos | Acceso | Para aprender |
|---|---|---|---|
| [GitHub](https://github.com) | Código, ramas, pull requests y revisión. Todo cambio entra por una rama y un pull request que revisa el fundador. main es lo que leen los agentes. | Cuenta propia con verificación en dos pasos; el fundador te invita a cada repo con el permiso de tu rol. | [enlace](https://docs.github.com/es/get-started/start-your-journey) |
| [Claude y Claude Code (Anthropic)](https://claude.ai) | Agente de investigación y riesgo del laboratorio; también el asistente de programación del equipo. En Finance-tool, Claude analiza cada hora, revisa propuestas y puede vetar; no ejecuta. Para programar, Claude Code trabaja sobre los repos. | Cuenta propia. Nunca uses la del fundador: tiene conectores a Binance, Supabase y Gmail. | [enlace](https://code.claude.com/docs) |
| [ChatGPT / Codex (OpenAI)](https://chatgpt.com) | Agente de trading y ejecución: el único que envía órdenes a Binance. Propone, revisa las propuestas de Claude y ejecuta las que quedan READY_TO_EXECUTE. Su prompt de arranque está en docs/codex-onboarding.md. | Cuenta propia si la necesitas para programar. La cuenta de Codex con permiso de trading es solo del fundador. | [enlace](https://developers.openai.com/codex) |
| [Supabase](https://supabase.com) | Postgres gestionado. En Finance-tool es el diario compartido y append-only entre agentes. Historia, propuestas, revisiones, trades, estrategias, sentimiento, investigación y el registro del equipo (team_members). | Rol personal de solo lectura team_<tu_handle> (lo crea el fundador). Nunca la clave service_role. | [enlace](https://supabase.com/docs) |
| [Binance (subcuenta agéntica, Spot)](https://www.binance.com) | El exchange donde opera el laboratorio. Es la fuente de verdad de precios, saldos y órdenes. Solo la usan los agentes: Claude en solo lectura y Codex con trading Spot. Sin margen, préstamos ni futuros. | Ninguno para miembros del equipo; la base rechaza concederlo. Los precios públicos se consultan sin cuenta. | [enlace](https://developers.binance.com/docs/binance-spot-api-docs) |
| [Gmail](https://mail.google.com) | Canal de alertas de los agentes al fundador. Avisos IMPORTANTES: propuestas aprobadas con su ventana de veto y órdenes de respaldo si el ejecutor no responde. | Solo el fundador. |  |
| [Vercel](https://vercel.com) | Hosting de las aplicaciones web (Next.js). Despliegue de PraxiGuard. | Lo da el fundador cuando haga falta desplegar. | [enlace](https://vercel.com/docs) |
| [Docker](https://www.docker.com) | Contenedores para correr Postgres y Supabase en tu PC. Pruebas del esquema de Finance-tool (Postgres 17) y Supabase local de PraxiGuard. | Instalación local (Docker Desktop). | [enlace](https://docs.docker.com/get-started/) |

## Open source

| Proyecto | Licencia | Para qué | Dónde | Para aprender |
|---|---|---|---|---|
| [Python 3.11+](https://www.python.org) | PSF-2.0 | Lenguaje de Finance-tool y Zyneath. Las pruebas usan unittest de la biblioteca estándar. | finance-tool, zyneath | [enlace](https://docs.python.org/es/3/tutorial/) |
| [NumPy](https://github.com/numpy/numpy) | BSD-3-Clause | Indicadores, backtest y validación estadística (ai_trading_lab/). | finance-tool | [enlace](https://numpy.org/doc/stable/user/absolute_beginners.html) |
| [vaderSentiment](https://github.com/cjhutto/vaderSentiment) | MIT | Tono de los titulares, con un léxico cripto propio (ai_trading_lab/sentiment.py). | finance-tool |  |
| [psycopg 3](https://github.com/psycopg/psycopg) | LGPL-3.0 | Conexión a Postgres del centro de mando y de la ingesta. | finance-tool |  |
| [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) | Apache-2.0 | Gráfico de velas del centro de mando (copia en dashboard/static/vendor). | finance-tool |  |
| [PostgreSQL](https://www.postgresql.org) | PostgreSQL | La base de todo: tablas append-only, vistas de estado y reglas que valida la propia base. | finance-tool, praxiguard | [enlace](https://www.postgresql.org/docs/current/tutorial.html) |
| [Supabase (CLI y supabase-js)](https://github.com/supabase/supabase) | Apache-2.0 / MIT | Supabase local para desarrollo y cliente en la web. | praxiguard |  |
| [Node.js y TypeScript](https://nodejs.org) | MIT / Apache-2.0 | Entorno y lenguaje de las aplicaciones web. | praxiguard | [enlace](https://www.typescriptlang.org/docs/handbook/intro.html) |
| [Next.js y React](https://github.com/vercel/next.js) | MIT | Framework web. | praxiguard | [enlace](https://nextjs.org/learn) |
| [Vercel AI SDK](https://github.com/vercel/ai) | Apache-2.0 | Llamadas a modelos de lenguaje desde la web. | praxiguard |  |
| [Zod](https://github.com/colinhacks/zod) | MIT | Validación de datos de entrada. | praxiguard |  |
| [Vitest, Playwright y ESLint](https://playwright.dev) | MIT / Apache-2.0 | Pruebas unitarias, pruebas de navegador y lint. | praxiguard |  |
| [requests, PyJWT y cryptography](https://github.com/pyca/cryptography) | Apache-2.0 / MIT / BSD | HTTP y firma de peticiones. Pocas dependencias a propósito: cada paquete es una puerta de entrada. | zyneath |  |
| [pytest y Ruff](https://github.com/astral-sh/ruff) | MIT | Pruebas y lint. | zyneath |  |

## Fuentes de datos

| Fuente | Para qué | Dónde |
|---|---|---|
| [Binance: API pública y data.binance.vision](https://data.binance.vision) | Velas en vivo (api.binance.com) e histórico oficial verificado por SHA-256 para el hard testing. Funding y largo/corto de futuros solo como dato. | finance-tool |
| [Sentimiento: Fear & Greed, RSS y Bluesky](https://alternative.me/crypto/fear-and-greed-index/) | Contexto, no señal: alternative.me, CoinDesk, Cointelegraph, Decrypt, r/CryptoCurrency, OilPrice, CNBC, Investing.com y Bluesky (tools/ingest_sentiment.py). | finance-tool |
| [DefiLlama](https://defillama.com) | Oferta de stablecoins y TVL de activos del mundo real tokenizados. | finance-tool |
| [arXiv (q-fin)](https://arxiv.org/list/q-fin/new) | Ingesta semanal de papers de estrategias (tools/ingest_sources.py). Quantpedia y SSRN entran a mano. | finance-tool |
| [Tesis de IA: SEC EDGAR, UN Comtrade, MOEA de Taiwán, GE Vernova, OpenFIGI](https://www.sec.gov/edgar/search/) | 13F, capex de los compradores de IA y oferta física (tools/ai_research.py, docs/plans/ai-infra-research.md). | finance-tool |

