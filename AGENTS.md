# AI Trading Lab — protocolo para agentes

Este archivo lo leen todos los agentes que trabajan en el proyecto (Claude, ChatGPT/Codex).
Las reglas del usuario (solo Spot, sin margen ni préstamos, 5 USDT máx., 1 posición, universo de 5 pares,
nada se ejecuta sin autorización explícita) mandan sobre todo lo que sigue.

## Roles

| Agente | `agent_id` | Binance | Rol |
|---|---|---|---|
| Claude | `claude` | Solo lectura | Investigación y riesgo. Propone y revisa propuestas (puede vetar); no ejecuta. |
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

## Buzón entre agentes

Supabase no despierta a nadie: cada agente revisa su buzón al empezar cada ejecución programada.

```sql
select * from v_pending_messages where to_agent_id = '<tu agent_id>' order by id;
select * from v_proposal_status where status not in ('EXECUTED', 'EXPIRED') order by created_at desc;
```

- Para pedir algo al otro agente: `insert into agent_messages (from_agent_id, to_agent_id, kind, related_ref, body, expires_at)`.
  `kind`: `REVIEW_REQUEST`, `REVIEW_DONE`, `EXECUTION_DONE`, `ALERT`, `INFO`.
- Al atenderlo: `insert into message_acks (message_id, acked_by_agent_id, outcome)`. Solo el destinatario puede hacerlo.
- Frecuencia: Claude revisa al cierre de cada vela de 4h (7:01, 11:01, 15:01 y 19:01 hora de Quito);
  ChatGPT/Codex, cada hora. Por eso una propuesta de Claude se revisa en menos de 1h y una de Codex puede
  esperar hasta 4h: ponle un `expires_at` realista.

## De la propuesta a la ejecución

Cualquiera de los dos agentes puede proponer. El otro revisa, el usuario autoriza y solo ChatGPT/Codex ejecuta.

1. El proponente inserta en `trade_proposals` y envía un `REVIEW_REQUEST` al otro agente con
   `related_ref = proposal_id`. La base rechaza símbolos fuera del universo, notional por encima del máximo
   (7 USDT) y niveles incoherentes.
2. El otro agente rehace el análisis con datos frescos, inserta en `risk_reviews`
   (`APPROVE` / `WAIT` / `REJECT` / `NEEDS_REASSESSMENT`), responde con `REVIEW_DONE` y da por atendido el
   mensaje. Nadie revisa su propia propuesta. `APPROVE` es solo análisis.
3. El usuario autoriza en el chat, con Claude o con Codex. El agente que recibe la autorización la registra
   en `execution_authorizations` citando el mensaje del usuario, y si no es el ejecutor, avisa con un `ALERT`.
4. **El ejecutor solo opera propuestas con `status = 'READY_TO_EXECUTE'` en `v_proposal_status`.** Justo antes
   de enviar la orden comprueba de nuevo precio, saldo y que la propuesta siga ahí: si el precio ya salió de
   la zona de entrada, no ejecuta y lo registra.
5. Tras ejecutar, inserta en `trades` con los datos de las órdenes reales de Binance y envía
   `EXECUTION_DONE` al otro agente. Si faltaba algún requisito, la base registra el trade igualmente, lo marca
   `gate_passed = false` y abre un evento crítico.
6. Al cerrar, inserta en `trade_closures`, con lecciones incluidas. Los stops no necesitan autorización:
   salir nunca se bloquea.

## Desacuerdos

No modifiques ni contradigas en silencio el registro del otro agente. Escribe tu propio registro
(`risk_reviews.disagreement_note` o un `analyses` nuevo) con la evidencia de mercado que sostiene tu postura.

## Eventos

Riesgos, incidencias y decisiones pendientes van en `events`. Para cerrar uno, inserta otro evento con
`resolves_event_id` apuntando al original.
