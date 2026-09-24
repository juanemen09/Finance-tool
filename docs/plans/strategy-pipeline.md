# Plan: pipeline de estrategias con validación obligatoria

Estado: **aprobado por el usuario el 2026-09-24**, con estas decisiones: solo se proponen operaciones
respaldadas por estrategias `LIVE_ELIGIBLE` en cuanto exista alguna; numpy como dependencia; ingesta y
pruebas semanales, re-test mensual. Tamaño: grande.

## Objetivo

Alimentar el laboratorio con estrategias publicadas en fuentes reales, traducirlas a reglas ejecutables y
**no usar ninguna hasta que pase una batería de pruebas diseñada para rechazar edges falsos**. Las que pasan
se vigilan en papel y se vuelven a probar periódicamente para detectar si el edge se degrada.

## Lo que encontró la investigación (2026-09-24)

| Fuente | Acceso | Uso en el plan |
|---|---|---|
| **arXiv** (q-fin.TR, q-fin.PM, q-fin.ST, q-fin.CP) | API pública y gratuita (`export.arxiv.org/api/query`); probada, devuelve papers de agosto de 2026 sobre cripto | Ingesta automática semanal |
| **Quantpedia** | Bloquea el acceso automatizado (HTTP 466 incluso en RSS y robots.txt) | Entrada **manual**: tú pegas el enlace o el resumen de una estrategia y el agente la registra. No se evade su protección |
| **SSRN** | Sin API pública | Entrada manual por enlace |
| **Binance** | Velas de 1h oficiales en `data.binance.vision` (ZIP mensuales con checksum) y en la API | Datos de backtest. BTC desde 2017-08, ETH/LINK/SOL de años; **ONDO solo desde 2025-04** (~17 meses) |

Derechos de autor: solo se guardan metadatos, enlace, un resumen propio y las reglas formalizadas. Nunca el
texto del paper o de Quantpedia.

Expectativa honesta: la literatura documenta que las anomalías publicadas pierden buena parte de su
rendimiento fuera de muestra y tras publicarse, y muchas se diseñaron para acciones, carteras amplias o
rebalanceos mensuales. Con 5 pares, 1 posición, 1h/4h y 0,2 % de coste por operación completa, **lo esperable
es que la mayoría no pase las pruebas**. Ese es el propósito: rechazar pronto y barato.

## Ciclo de vida (append-only en Supabase)

`DISCOVERED` → `NOT_APPLICABLE` | `CANDIDATE` → `PREREGISTERED` → `TESTING` → `REJECTED` | `PAPER` →
`LIVE_ELIGIBLE` (**solo con tu aprobación**) → `DEGRADED` → `RETIRED`

Cada cambio de estado es una fila nueva con motivo y evidencia; nada se edita.

## Protocolo de hard testing (obligatorio)

1. **Pre-registro inmutable antes de tocar datos**: hipótesis y razón económica, reglas exactas, rejilla de
   parámetros acotada, activos, temporalidad, períodos, métricas y umbrales de aprobación. Si luego se
   cambia algo, es un pre-registro nuevo y cuenta como otro intento.
2. **Datos verificados**: ZIP oficiales de Binance con checksum SHA-256; se registra el hash de los datos y el
   commit del código de cada prueba (reproducibilidad).
3. **Ejecución realista**: señal con la vela cerrada, entrada en la apertura de la siguiente; comisión 0,1 %
   por lado + deslizamiento; restricción de minNotional; 1 posición; stop antes que target si ambos caen en
   la misma vela. Prueba automática anti-lookahead.
4. **Separación de datos**: desarrollo → walk-forward (entrenar 12 meses, probar 3, avanzar) → **reserva final
   de 6 meses que solo se usa una vez**, al final.
5. **Métricas y mínimos**: expectativa neta por operación, profit factor, máximo drawdown, Sharpe y Sortino;
   al menos 100 operaciones en desarrollo y 30 fuera de muestra.
6. **Robustez**: meseta de parámetros (≥ 70 % de los vecinos del óptimo también rentables, no un pico
   aislado), consistencia por activo, por año y por régimen de BTC; sigue rentable con el **doble de costes**.
7. **Estadística contra el azar**:
   - intervalo de confianza bootstrap del retorno medio por operación que excluya el 0;
   - Monte Carlo reordenando operaciones para la distribución de drawdown;
   - **benchmark de entradas aleatorias** con igual número de operaciones y duración: la estrategia debe
     superar el percentil 95;
   - comparación con comprar y mantener;
   - **Deflated Sharpe Ratio** corrigiendo por el número total de intentos registrados en la base (incluidos
     los rechazados), para que probar muchas ideas no fabrique un ganador por suerte.
8. **Calibración del propio test** (la prueba de que el test sirve): sobre paseos aleatorios sintéticos debe
   rechazar casi todo (tasa de falsos positivos ≤ 5 %), y sobre datos con un edge sembrado debe detectarlo.
9. **Papel antes que dinero**: una estrategia `PAPER` emite señales en los ciclos automáticos, se puntúan con
   `decision_scores` y debe acumular al menos 20 señales, o 4 semanas, con resultados dentro del intervalo
   esperado del backtest. Solo entonces se te propone `LIVE_ELIGIBLE`.
10. **Re-test mensual**: ventana móvil fuera de muestra; si cae bajo el límite inferior esperado, pasa a
    `DEGRADED` y deja de poder respaldar operaciones.

## Tareas (rebanadas verticales, cada una con pruebas primero)

1. **Esquema** (migración): `strategy_sources`, `strategies`, `strategy_status_events`,
   `test_preregistrations`, `backtest_runs`, `strategy_signals`; vistas `v_strategy_board` y
   `v_trial_count`. Pruebas SQL en transacción revertida, como las actuales.
2. **Datos**: descarga y caché local de ZIP de Binance con verificación de checksum (`data/raw/`, fuera de git).
3. **Motor de backtest**: velas cerradas, entrada en la siguiente apertura, costes, minNotional, 1 posición,
   stop/target conservador. Pruebas: anti-lookahead, costes, orden stop/target.
4. **Validación**: walk-forward, bootstrap, Monte Carlo, entradas aleatorias, meseta de parámetros, Deflated
   Sharpe. Pruebas de calibración con paseos aleatorios y edge sembrado.
5. **Ingesta**: `tools/ingest_sources.py` (arXiv) con deduplicado; salida para que el agente clasifique
   aplicabilidad y escriba el resumen propio. Entrada manual para Quantpedia/SSRN.
6. **Tres estrategias de referencia**, elegidas entre las que la ingesta encuentre con evidencia en cripto
   (por ejemplo, seguimiento de tendencia, reversión de corto plazo y estacionalidad intradía), pasadas por
   el protocolo completo de principio a fin como prueba del pipeline.
7. **Automatización**: tarea semanal (lunes 8:00, Quito) de ingesta + pruebas pendientes + re-test mensual,
   con correo solo si hay cambios de estado; los ciclos de 4h pasan a registrar las señales de las
   estrategias `PAPER` y `LIVE_ELIGIBLE`.
8. **Codex**: sección en `AGENTS.md`; puede proponer candidatas y revisar resultados, pero no puede marcar
   `LIVE_ELIGIBLE`.

## Decisiones que necesito de ti

1. **Política de operación** una vez exista una estrategia validada: ¿solo se proponen operaciones respaldadas
   por una estrategia `LIVE_ELIGIBLE` (recomendado), o se siguen permitiendo propuestas discrecionales?
2. **Dependencias**: no hay numpy/pandas instalados. Python puro alcanza (≈ 80.000 velas por activo) pero es
   más lento; numpy acelera bootstrap y rejillas. ¿Instalo numpy desde PyPI?
3. **Cadencia**: ingesta y pruebas semanales, re-test mensual, con Sonnet 5 si la app lo permite.
