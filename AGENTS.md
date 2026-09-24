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
- Frecuencia: Claude revisa cada hora (unos minutos después del cierre de 1h); ChatGPT/Codex, cada 15
  minutos (si no hay nada pendiente, termina sin analizar). Una propuesta se revisa en menos de 1h: ponle un
  `expires_at` realista.

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

## Estrategias: fuentes, hard testing y uso

Detalle completo en `docs/plans/strategy-pipeline.md`. Lo esencial:

- **Fuentes:** arXiv entra por ingesta automática semanal (`tools/ingest_sources.py`). Quantpedia y SSRN
  bloquean o no ofrecen acceso automatizado: entran cuando el usuario pega un enlace o un resumen en el chat
  de cualquier agente (`strategy_sources.submitted_by = 'user'`). Nunca se evade la protección de un sitio ni
  se copia su texto: solo metadatos, enlace y un resumen propio.
- **Ciclo de vida** (`strategy_status_events`, lo valida la base): `DISCOVERED` → `CANDIDATE` |
  `NOT_APPLICABLE` → `PREREGISTERED` → `TESTING` → `REJECTED` | `PAPER` → `LIVE_ELIGIBLE` (**solo el
  usuario**) → `DEGRADED` → `RETIRED`.
- **Pre-registro antes de mirar datos:** `test_preregistrations` con hipótesis, rejilla, activos, períodos,
  costes y umbrales, más el commit del código. Cambiar algo después es otro pre-registro y suma intentos en
  `v_trial_count`, que alimenta el Deflated Sharpe.
- **Hard test:** `python -m tools.run_hard_test <prereg.json>`. Solo con código en un commit limpio. La
  reserva final se usa una única vez por estrategia (la base rechaza un segundo uso).
- **Papel:** una estrategia `PAPER` emite señales en `strategy_signals` en cada ciclo, pero no respalda
  operaciones. Tras ≥ 4 semanas y ≥ 20 operaciones hacia delante se revisa (`--kind PAPER_REVIEW`); si pasa,
  se propone `LIVE_ELIGIBLE` al usuario.
- **Política del usuario (solo validadas):** en cuanto exista una estrategia `LIVE_ELIGIBLE`, toda compra en
  `trade_proposals` debe llevar el `strategy_id` de una `LIVE_ELIGIBLE` (la base rechaza las demás). Las ideas
  discrecionales se registran en `analyses` y se puntúan, pero no se proponen.
- **Re-test mensual** de cada `LIVE_ELIGIBLE`; si falla, pasa a `DEGRADED` y deja de respaldar operaciones.
- Implementar una familia nueva de estrategia es un cambio de código: se hace en una sesión supervisada,
  con pruebas, nunca desde una tarea automática.
- **Estrategias con salida por señal** (p. ej. `channel_trend`, `tsmom`): al entrar se coloca en Binance una
  orden stop-loss en `invalidation`; no se coloca take profit. `targets[1]` de la propuesta es solo una
  referencia de 2R para calcular riesgo/beneficio. La salida la marca la regla de la estrategia tras el
  cierre de su vela (por ejemplo, cierre diario por debajo del mínimo de 10 días): quien la detecte envía un
  `ALERT` y el ejecutor vende.
- Temporalidades y ventanas de prueba (12 meses de entrenamiento, 3 de prueba y 6 de reserva): `1h` 8760 /
  2190 / 4380 velas; `4h` 2190 / 548 / 1095; `1d` 365 / 91 / 183. Las velas de 4h y 1d se construyen desde 1h
  verificado y coinciden con las nativas de Binance.

### Estado a 2026-09-24
- `S-CHANNEL-1D` (canal de Donchian diario: entra si el cierre supera el máximo de 20 días, sale si cierra
  por debajo del mínimo de 10, stop 2 ATR) pasó el hard testing completo, incluida la reserva final, y está en
  **PAPER**. Pérdida típica por operación perdedora ≈ -8 % (≈ -0,55 USDT con 7 USDT); ~7 operaciones al año
  con una posición. Pasa a `LIVE_ELIGIBLE` solo si el usuario lo decide.
- Rechazadas: las tres de 1h, las de compresión (4h y 1d), y por poco el canal y el momentum de 4h (Deflated
  Sharpe 0,71) y el momentum diario (percentil 92 frente al azar).

## Autorización permanente con ventana de veto

Aplicada por el usuario el 2026-09-24 (`standing_authorizations`, fila vigente = la última). Una propuesta
queda ejecutable **sin** el "autorizo" del usuario solo si `auto_authorization_status(proposal_id, now())`
devuelve `auto_ok = true`, es decir, si se cumplen TODAS estas condiciones:

- estrategia `LIVE_ELIGIBLE` (`trade_proposals.strategy_id`);
- último veredicto del otro agente = `APPROVE`, y pasaron 15 minutos desde ese veredicto;
- sin veto del usuario (`user_vetoes`), no expirada y no ejecutada;
- pérdida estimada hasta `invalidation` (con comisión y deslizamiento) ≤ 0,8 USDT;
- relación riesgo/beneficio a `targets[1]` ≥ 1,5;
- pérdidas cerradas de los últimos 7 días > -1 USDT;
- ninguna alerta `permissions_review` abierta (permisos del ejecutor corregidos) y ninguna posición abierta.

`v_executable_proposals.authorization_mode` dice si la autorización fue del usuario (`USER`) o permanente
(`STANDING`). **Veto:** si el usuario escribe a cualquier agente "veto <proposal_id>", ese agente inserta en
`user_vetoes` citando el mensaje, inmediatamente. Cuando un agente aprueba una propuesta, el correo al usuario
debe decir que tiene 15 minutos para vetarla. Nada de esto cambia la regla de salida: los stops y las salidas
por señal nunca requieren autorización.

## Desacuerdos

No modifiques ni contradigas en silencio el registro del otro agente. Escribe tu propio registro
(`risk_reviews.disagreement_note` o un `analyses` nuevo) con la evidencia de mercado que sostiene tu postura.

## Eventos

Riesgos, incidencias y decisiones pendientes van en `events`. Para cerrar uno, inserta otro evento con
`resolves_event_id` apuntando al original.
