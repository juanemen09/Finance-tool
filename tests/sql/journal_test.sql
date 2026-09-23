-- Pruebas de comportamiento del diario compartido. Todo corre en una transacción que se revierte,
-- así que se puede ejecutar contra una base real sin dejar rastro:
--   psql -v ON_ERROR_STOP=1 -f tests/sql/journal_test.sql
begin;

create function pg_temp.expect_error(stmt text, fragment text) returns void language plpgsql as $$
begin
  execute stmt;
  raise exception 'Se esperaba un error con "%" y no hubo ninguno: %', fragment, stmt;
exception when others then
  if sqlerrm like 'Se esperaba un error%' then raise; end if;
  if position(fragment in sqlerrm) = 0 then
    raise exception 'Error distinto al esperado. Esperado "%", recibido "%"', fragment, sqlerrm;
  end if;
end $$;

insert into agents (id, display_name, role) values
  ('claude', 'Claude', 'risk'), ('chatgpt', 'ChatGPT / Codex', 'execution');
insert into risk_limits (max_position_usdt, max_open_positions, universe, executor_agent_id, set_by, note)
values (5, 1, array['BTCUSDT','ETHUSDT','SOLUSDT','LINKUSDT','ONDOUSDT'], 'chatgpt', 'user', 'test');

-- Append-only
select pg_temp.expect_error($$update agents set role = 'x' where id = 'claude'$$, 'append-only');
select pg_temp.expect_error($$delete from agents where id = 'claude'$$, 'append-only');
select pg_temp.expect_error($$truncate events$$, 'append-only');

-- created_at lo fija la base
insert into events (agent_id, kind, severity, message, created_at)
values ('claude', 'test', 'info', 'backdated', '2000-01-01');
do $$ begin
  assert (select created_at from events where message = 'backdated') = now(), 'created_at no fue forzado a now()';
end $$;

-- Niveles de una BUY_CANDIDATE
select pg_temp.expect_error($$
  insert into analyses (analysis_id, agent_id, assets_analyzed, timeframes, market_data_as_of, market_regime,
    thesis, proposed_action, symbol, entry_low, entry_high, invalidation, targets, valid_until, confidence_context)
  values ('A-bad', 'claude', '{BTCUSDT}', '{1h}', now(), 'x', 'x', 'BUY_CANDIDATE', 'BTCUSDT',
    100, 101, 100.5, '{110}', now() + interval '1 day', 'x')$$, 'invalidación');

-- Propuestas: universo, tamaño, niveles
select pg_temp.expect_error($$
  insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high, invalidation, targets,
    notional_usdt, thesis, cancel_conditions, expires_at)
  values ('P-doge', 'chatgpt', 'DOGEUSDT', 'BUY', 1, 2, 0.5, '{3}', 5, 'x', 'x', now() + interval '1 day')$$,
  'fuera del universo');
select pg_temp.expect_error($$
  insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high, invalidation, targets,
    notional_usdt, thesis, cancel_conditions, expires_at)
  values ('P-big', 'chatgpt', 'BTCUSDT', 'BUY', 82000, 82600, 80900, '{85100}', 6, 'x', 'x', now() + interval '1 day')$$,
  'supera el máximo');

insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high, invalidation, targets,
  notional_usdt, thesis, cancel_conditions, expires_at)
values ('P-1', 'chatgpt', 'BTCUSDT', 'BUY', 82000, 82600, 80900, '{85100,87300}', 5, 'pullback', 'BTC < 80100',
  now() + interval '1 day');

-- Nadie revisa lo suyo
select pg_temp.expect_error($$
  insert into risk_reviews (review_id, proposal_id, reviewer_agent_id, verdict, market_data_as_of, reasoning)
  values ('R-self', 'P-1', 'chatgpt', 'APPROVE', now(), 'x')$$, 'propia propuesta');

-- Autorización del usuario antes del APPROVE no basta: el último veredicto es WAIT
insert into execution_authorizations (proposal_id, authorized_by, recorded_by_agent_id, user_message_quote)
values ('P-1', 'user', 'chatgpt', 'dale');
insert into risk_reviews (review_id, proposal_id, reviewer_agent_id, verdict, market_data_as_of, reasoning)
values ('R-1', 'P-1', 'claude', 'WAIT', now(), 'entrada tardía');
do $$ begin
  assert not exists (select 1 from v_executable_proposals where proposal_id = 'P-1'), 'WAIT no debe ser ejecutable';
end $$;

insert into risk_reviews (review_id, proposal_id, reviewer_agent_id, verdict, market_data_as_of, reasoning)
values ('R-2', 'P-1', 'claude', 'APPROVE', now(), 'retesteo confirmado');
insert into execution_authorizations (proposal_id, authorized_by, recorded_by_agent_id, user_message_quote)
values ('P-1', 'user', 'chatgpt', 'autorizo P-1');
do $$ begin
  assert exists (select 1 from v_executable_proposals where proposal_id = 'P-1'), 'APPROVE + autorización debe ser ejecutable';
end $$;

-- Un ejecutor no designado queda marcado y genera evento crítico, pero el trade se registra
insert into trades (trade_ref, proposal_id, executor_agent_id, symbol, side, executed_at, entry_price, quantity,
  notional_usdt, fee_amount, fee_asset, fee_usdt, binance_order_ids, market_regime, entry_thesis, invalidation, stop, targets)
values ('Trade #901', 'P-1', 'claude', 'BTCUSDT', 'BUY', now(), 82500, 0.00006, 4.95, 0.00000006, 'BTC', 0.005,
  '{1}', 'x', 'x', 80900, 80900, '{85100}');
do $$ begin
  assert (select gate_passed from trades where trade_ref = 'Trade #901') = false, 'ejecutor no designado debió fallar el gate';
  assert exists (select 1 from v_open_events where kind = 'protocol_violation' and related_ref = 'Trade #901'),
    'falta el evento crítico';
end $$;

-- Con una posición abierta, un segundo trade (aunque sea del ejecutor correcto) viola el máximo
insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high, invalidation, targets,
  notional_usdt, thesis, cancel_conditions, expires_at)
values ('P-2', 'chatgpt', 'ETHUSDT', 'BUY', 2635, 2650, 2600, '{2715}', 5, 'x', 'x', now() + interval '1 day');
insert into risk_reviews (review_id, proposal_id, reviewer_agent_id, verdict, market_data_as_of, reasoning)
values ('R-3', 'P-2', 'claude', 'APPROVE', now(), 'ok');
insert into execution_authorizations (proposal_id, authorized_by, recorded_by_agent_id, user_message_quote)
values ('P-2', 'user', 'chatgpt', 'autorizo P-2');
insert into trades (trade_ref, proposal_id, executor_agent_id, symbol, side, executed_at, entry_price, quantity,
  notional_usdt, fee_amount, fee_asset, fee_usdt, binance_order_ids, market_regime, entry_thesis, invalidation, stop, targets)
values ('Trade #902', 'P-2', 'chatgpt', 'ETHUSDT', 'BUY', now(), 2645, 0.0019, 5.0, 0.0000019, 'ETH', 0.005,
  '{2}', 'x', 'x', 2600, 2600, '{2715}');
do $$ begin
  assert (select gate_detail from trades where trade_ref = 'Trade #902') like '%posición(es) abierta(s)%',
    'debió detectar el máximo de posiciones';
end $$;

-- Cierre y estadísticas
insert into trade_closures (trade_ref, recorded_by_agent_id, closed_at, exit_reason, exit_price, quantity, fee_amount,
  fee_asset, fee_usdt, binance_order_ids, pnl_usdt, pnl_pct, went_right, went_wrong, lessons)
values ('Trade #901', 'chatgpt', now(), 'TARGET', 85100, 0.00006, 0.0051, 'USDT', 0.0051, '{3}', 0.146, 2.95, 'x', 'x', 'x'),
       ('Trade #902', 'chatgpt', now(), 'STOP', 2600, 0.0019, 0.0049, 'USDT', 0.0049, '{4}', -0.095, -1.9, 'x', 'x', 'x');
do $$
declare p record;
begin
  select * into p from v_performance;
  assert p.closed_trades = 2 and p.wins = 1, 'conteo de trades';
  assert p.realized_pnl_usdt = 0.051, format('pnl realizado %s', p.realized_pnl_usdt);
  assert p.profit_factor = round(0.146 / 0.095, 4), format('profit factor %s', p.profit_factor);
  assert not exists (select 1 from v_open_positions), 'no debería quedar posición abierta';
end $$;
select pg_temp.expect_error($$
  insert into trade_closures (trade_ref, recorded_by_agent_id, closed_at, exit_reason, exit_price, quantity, fee_amount,
    fee_asset, fee_usdt, binance_order_ids, pnl_usdt, pnl_pct, went_right, went_wrong, lessons)
  values ('Trade #901', 'chatgpt', now(), 'MANUAL', 1, 1, 0, 'USDT', 0, '{5}', 0, 0, 'x', 'x', 'x')$$, 'duplicate key');

-- Resolver un evento lo saca de v_open_events
insert into events (agent_id, kind, severity, message, resolves_event_id)
select 'claude', 'resolution', 'info', 'revisado', id from events where related_ref = 'Trade #901';
do $$ begin
  assert not exists (select 1 from v_open_events where related_ref = 'Trade #901'), 'el evento resuelto sigue abierto';
end $$;

-- Sin acceso para roles públicos
set local role anon;
select pg_temp.expect_error($$select * from analyses$$, 'permission denied');
select pg_temp.expect_error($$select * from v_performance$$, 'permission denied');
reset role;

select 'journal_test: OK' as result;
rollback;
