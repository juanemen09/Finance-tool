# TimesFM 3.0 en el laboratorio: prueba hacia delante en papel

Pedido del usuario (2026-09-30), para investigación personal y no comercial: integrar el modelo de pronóstico
TimesFM 3.0 al algoritmo de Spot. Este documento fija **antes de ver resultados** cómo se decide si sirve.

## Por qué solo hacia delante

TimesFM se preentrenó con más de un billón de puntos de series públicas. Casi seguro incluyen el historial de
BTC, ETH, SOL, LINK y ONDO. Un backtest sobre ese historial mediría lo que el modelo memorizó, no lo que sabe
pronosticar. Por eso no hay hard test sobre el pasado: solo cuentan los pronósticos hechos desde el 2026-09-30,
puntuados cuando llega el precio real.

## Qué corre y cuándo

- **Cada día, a las 19:10 de Quito** (00:10 UTC, tras el cierre diario), con reintentos a las 21:10 y a las 23:10 si
  falta memoria. Lo lanza una tarea del Programador de tareas de Windows (`tools/tsfm_daily.cmd`), sin gastar
  créditos de ningún agente.
- **`tools.tsfm_forecast`** corre en el entorno de TimesFM (`C:\TimesFM_Research\.venv`). Pronostica el logaritmo
  del cierre diario de los 5 pares con 1000 días de contexto, a 1, 3 y 7 días, con los cuantiles p10 a p90.
- **Referencia.** Con cada pronóstico se guarda la de un paseo aleatorio: el último cierre por los cuantiles
  empíricos del retorno a ese horizonte en el último año.
- **`tools.tsfm_ingest`** inserta los pronósticos en `forecasts` y puntúa los vencidos en `forecast_outcomes`.
  Guarda la pérdida cuantil (pinball) del modelo y de la referencia, si acertó la dirección y si el precio cayó
  dentro de p10–p90.
- **Vistas:** `v_forecast_latest` (último pronóstico por activo y horizonte) y `v_forecast_skill` (resultados
  acumulados).

## Criterio pre-registrado (no se cambia después de mirar)

Evaluación única cuando haya **60 cierres diarios** de pronósticos puntuados a 7 días (unos 300 pronósticos, hacia
el 2026-12-06). TimesFM "sirve" solo si se cumplen las tres condiciones:

1. **Skill frente al paseo aleatorio > 0** a 7 días, sumando los 5 activos, con el límite inferior del intervalo de
   confianza del 95 % por encima de 0. El intervalo sale de un bootstrap por bloques de fechas de origen, porque
   los pronósticos de días seguidos se solapan y no son independientes.
2. **Acierto de dirección a 7 días > 55 %.** La significancia se mide agrupando por fecha de origen, por el mismo
   solapamiento.
3. **Cobertura de la banda p10–p90 entre 70 % y 90 %**: bandas calibradas, ni demasiado estrechas ni demasiado
   anchas.

Si no cumple alguna, TimesFM queda como contexto y no se vuelve a probar con otra combinación de horizontes o
activos: cada variante nueva sumaría intentos y haría "encontrar" algo por azar.

Si cumple las tres, se pre-registra `S-CHANNEL-1D-TSFM`: S-CHANNEL-1D sin entrar cuando la mediana a 7 días
pronostica un retorno negativo. Irá en papel hacia delante, con las reglas de siempre: al menos 4 semanas y 20
operaciones antes de proponerla al usuario. Pasa a LIVE_ELIGIBLE solo si el usuario lo decide.

## Reglas mientras tanto

- **Contexto, no señal.** Los análisis de Claude citan el pronóstico de TimesFM del activo, como hacen con el
  sentimiento. Ningún agente propone, aprueba, rechaza ni dimensiona una operación por él.
- **Licencia.** Los pesos de TimesFM 3.0 tienen la licencia TimesFM Non-Commercial v1.0. El usuario declaró que el
  laboratorio es investigación personal y no comercial.
