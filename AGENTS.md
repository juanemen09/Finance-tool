# AI Trading Lab — protocolo para agentes

Este archivo lo leen todos los agentes que trabajan en el proyecto (Claude, ChatGPT/Codex).
Las reglas del usuario (solo Spot, sin margen ni préstamos, 5 USDT máx., 1 posición, universo de 5 pares,
nada se ejecuta sin autorización explícita) mandan sobre todo lo que sigue.

## Roles

| Agente | `agent_id` | Binance | Rol |
|---|---|---|---|
| Claude | `claude` | Solo lectura | Investigación y riesgo. Revisa propuestas y veta; no ejecuta. |
| ChatGPT / Codex | `chatgpt` | Lectura + trading spot | Propone y ejecuta. Único ejecutor (`risk_limits.executor_agent_id`). |

## Fuentes de verdad

- **Binance** (MCP del agente) es la verdad para precios, saldos, órdenes y posiciones. Nunca uses un
  dato de mercado viejo de Supabase como actual.
- **Supabase** es el diario compartido y append-only: historia, propuestas, revisiones y resultados.
  No se edita ni se borra nada. Para corregir, inserta un registro nuevo que lo diga.

## Al empezar cada sesión

```sql
select * from v_current_risk_limits;
select * from v_open_events order by id;
select * from v_open_positions;
select * from v_latest_portfolio;
select * from trade_proposals order by id desc limit 10;
select * from risk_reviews order by id desc limit 10;
select * from analyses order by id desc limit 10;
```

Luego consulta Binance directamente y compara con `v_latest_portfolio`. Si no cuadran, registra un
`events` de severidad `warning`.

## Ciclo de análisis

1. Datos frescos: `python -m tools.market_scan --json`, o las herramientas de mercado de tu MCP.
2. Inserta un registro en `analyses`. Una `BUY_CANDIDATE` exige `symbol`, `entry_low`, `entry_high`,
   `invalidation`, `targets` y `valid_until`; la base rechaza niveles incoherentes.
3. **Competición a ciegas:** usa el mismo `cycle_id` que el otro agente (formato `AAAA-MM-DDTHHZ`, la hora
   UTC del cierre de 1h analizado) y **no leas el análisis del otro para ese ciclo antes de escribir el tuyo**.
   `v_agent_scoreboard` compara resultados cuando `tools.score_decisions` los puntúa.

## De la propuesta a la ejecución

1. El proponente inserta en `trade_proposals`. La base rechaza símbolos fuera del universo, notional por
   encima del máximo y niveles incoherentes.
2. El otro agente inserta en `risk_reviews` (`APPROVE` / `WAIT` / `REJECT` / `NEEDS_REASSESSMENT`) después
   de rehacer el análisis con datos frescos. Nadie revisa su propia propuesta. `APPROVE` es solo análisis.
3. El usuario autoriza en el chat. El agente que recibe la autorización la registra en
   `execution_authorizations` citando el mensaje del usuario.
4. **El ejecutor solo opera propuestas presentes en `v_executable_proposals`.**
5. Tras ejecutar, inserta en `trades` con los datos de las órdenes reales de Binance. Si faltaba algún
   requisito, la base registra el trade igualmente, lo marca `gate_passed = false` y abre un evento crítico.
6. Al cerrar, inserta en `trade_closures`, con lecciones incluidas. Los stops no necesitan autorización:
   salir nunca se bloquea.

## Desacuerdos

No modifiques ni contradigas en silencio el registro del otro agente. Escribe tu propio registro
(`risk_reviews.disagreement_note` o un `analyses` nuevo) con la evidencia de mercado que sostiene tu postura.

## Eventos

Riesgos, incidencias y decisiones pendientes van en `events`. Para cerrar uno, inserta otro evento con
`resolves_event_id` apuntando al original.
