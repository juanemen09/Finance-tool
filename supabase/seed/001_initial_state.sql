-- Estado inicial del diario. Se aplica una sola vez, después de la migración.
-- La foto de la cuenta NO va aquí: se toma en vivo de Binance al sembrar, nunca de un valor copiado.
-- Todo o nada: el diario es append-only, una carga a medias no se podría deshacer.
begin;

insert into public.agents (id, display_name, role) values
  ('claude', 'Claude', 'Quantitative Research / Risk Agent. Solo lectura en Binance; revisa y veta, no ejecuta.'),
  ('chatgpt', 'ChatGPT / Codex', 'Trading / Execution Agent. Único con permiso de trading en la subcuenta agéntica.');

insert into public.risk_limits (max_position_usdt, max_open_positions, universe, executor_agent_id, set_by, note)
values (
  5.00, 1, array['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'ONDOUSDT'], 'chatgpt', 'user',
  'Hard constraints del usuario (prompt AI Trading Lab, 2026-09-23): máx. 5 USDT por posición, 1 posición abierta, '
  || 'universo de 5 pares. Ejecutor chatgpt: es el único agente con permiso de trading en Binance; pendiente de '
  || 'confirmación explícita del usuario.'
);

insert into public.events (agent_id, kind, severity, message, related_ref) values
  ('claude', 'historical_context', 'info',
   'Trade #000 (primer ciclo, anterior a este diario): DO NOTHING. BTC con estructura 4h más fuerte y 1h más débil; '
   || 'ETH, SOL, LINK y ONDO más débiles o mixtos; capital en USDT. Fuente: contexto dado por el usuario, '
   || 'agente autor no registrado.', 'Trade #000'),
  ('claude', 'structural_risk', 'critical',
   'Binance exige minNotional = 5 USDT (applyMinToMarket) en los 5 pares y el tope por posición es 5 USDT: '
   || 'una posición de 5 USDT que baje o pierda la comisión en el activo base no puede venderse; el stop sería '
   || 'rechazado. Requiere que el usuario suba el tope (sugerido ~7 USDT) o acepte el riesgo.', 'risk_limits'),
  ('claude', 'permissions_review', 'warning',
   'La autorización OAuth del agente ChatGPT en Binance incluye permisos que las reglas prohíben o no necesita: '
   || 'préstamo de margen/reembolsos/transferencias, transferencia interna y lectura de la cuenta principal. '
   || 'Recomendado: reconectar con solo lectura + trading spot.', 'agent:chatgpt'),
  ('claude', 'permissions_verified', 'info',
   'Key OAuth de Claude verificada con wallet_getApiKeyPermission (creada 2026-09-23T22:58:56Z): enableReading=true; '
   || 'trading, margin, futures, retiros y transferencias en false; ipRestrict=false.', 'agent:claude');

insert into public.analyses (
  analysis_id, agent_id, cycle_id, related_trade_id, assets_analyzed, timeframes, market_data_as_of,
  market_regime, thesis, supporting_evidence, counterarguments, risk_factors, proposed_action,
  confidence_context, details
) values (
  'ATL-CLAUDE-2026-09-23-001', 'claude', '2026-09-23T22Z', 'Trade #001',
  array['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'ONDOUSDT'], array['4h', '1h'],
  '2026-09-23T22:05:16Z',
  'BTC 4h alcista puesto a prueba: la vela de las 12:00Z (~3x volumen) rompió el último mínimo creciente de 4h (85114) hasta 83500; '
  || 'precio en la EMA20 de 4h (~84.5k), sobre la EMA50 (82.1k). 1h bajista: bajo EMA20/50 (~85.1k), RSI 37, máximos decrecientes; '
  || 'rebote con volumen decreciente (RVOL 0.4). Altcoins cayeron más y a la vez; todas rompieron su mínimo de 4h.',
  'Sin ventaja a precios actuales: todos los activos están a mitad de rango tras una ruptura con volumen alto; comprar aquí es comprar '
  || 'bajo resistencia con invalidación a 1.5-3 % y primer objetivo a distancia similar (~1:1 antes de comisiones).',
  ('["BTC 4h: secuencia de mínimos 75065 -> 80126 -> 85114 rota a 83500 con 8306 BTC de volumen vs ~2.5k de media", '
  || '"Los cinco en 1h: cierre < EMA20 < EMA50; RSI14 32.7-38.3; RVOL de las últimas 3 velas 0.28-0.49", '
  || '"LINK bajo la EMA50 de 4h (12.34) y la EMA200 de 1h (12.31)", '
  || '"ONDO: ATR de 4h 3.95 %, apoyado en la EMA50 de 4h 0.408 sin reacción"]')::jsonb,
  ('["La tendencia de 4h de BTC/ETH/SOL sigue sobre EMA50 y EMA200: puede ser un retroceso normal", '
  || '"Posible clímax de venta: volumen alto + RSI de 1h sobrevendido puede preceder un rebote en V"]')::jsonb,
  ('["Estructural: minNotional 5 USDT = tope por posición; el stop no podría ejecutarse", '
  || '"Si BTC pierde 83.5k se abren 82.1k y 80.1k; las altcoins amplificarían"]')::jsonb,
  'DO_NOTHING',
  'Alta confianza en no operar ahora. Setups condicionales solo como vigilancia. Saldo no verificado en ese momento.',
  ('{"conditional_setups": ['
  || '{"symbol": "BTCUSDT", "entry": "82000-82600 tras cierre 1h de recuperación con RVOL > 1.2", "invalidation": 80900, "targets": [85100, 87300]},'
  || '{"symbol": "BTCUSDT", "entry": "cierre 1h > 85200 con RVOL > 1.2 y retesteo", "invalidation": 84200, "targets": [86700, 87300]},'
  || '{"symbol": "ETHUSDT", "entry": "2635-2650 con reacción alcista en 1h", "invalidation": 2600, "targets": [2715, 2789]}],'
  || '"cancel_all_if": "BTC pierde 80100 (último mínimo creciente de 4h)",'
  || '"data_source": "API pública de Binance /api/v3 (klines, ticker/24hr, exchangeInfo)"}')::jsonb
);

commit;
