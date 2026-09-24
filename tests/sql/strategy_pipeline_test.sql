-- Pruebas del ciclo de vida de estrategias. Transacción revertida: no deja rastro.
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

insert into agents (id, display_name, role) select 'claude', 'Claude', 'risk'
where not exists (select 1 from agents where id = 'claude');

insert into strategy_sources (source_key, source, url, title, submitted_by, own_summary)
values ('arxiv:test.0001', 'arxiv', 'https://arxiv.org/abs/test.0001', 't', 'claude', 'resumen propio');
insert into strategies (strategy_id, source_key, name, family, economic_rationale, rules_spec, applicability, created_by_agent_id)
values ('S-TEST', 'arxiv:test.0001', 'test', 'trend', 'r', '{}', '{}', 'claude');

-- La primera transición debe ser DISCOVERED, y no se pueden saltar pasos.
select pg_temp.expect_error($$insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
  values ('S-TEST', 'PAPER', 'x', 'claude', 'claude')$$, 'Transición no permitida');
insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id) values
  ('S-TEST', 'DISCOVERED', 'ingesta', 'claude', 'claude'),
  ('S-TEST', 'CANDIDATE', 'aplicable', 'claude', 'claude'),
  ('S-TEST', 'PREREGISTERED', 'pre-registro', 'claude', 'claude'),
  ('S-TEST', 'TESTING', 'en prueba', 'claude', 'claude');
select pg_temp.expect_error($$insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
  values ('S-TEST', 'LIVE_ELIGIBLE', 'x', 'claude', 'claude')$$, 'Transición no permitida');
select pg_temp.expect_error($$insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
  values ('S-TEST', 'CANDIDATE', 'x', 'intruso', 'claude')$$, 'decided_by');

-- PAPER exige un HARD_TEST aprobado.
select pg_temp.expect_error($$insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
  values ('S-TEST', 'PAPER', 'x', 'claude', 'claude')$$, 'PAPER exige');

insert into test_preregistrations (prereg_id, strategy_id, hypothesis, param_grid, symbols, bar_interval, holdout_bars,
  train_bars, test_bars, costs, thresholds, code_commit, created_by_agent_id)
values ('PR-TEST', 'S-TEST', 'h', '[{"a": 1}, {"a": 2}, {"a": 3}]', '{BTCUSDT}', '1h', 4380, 8760, 2190, '{}', '{}', 'abc', 'claude');
do $$ begin
  assert (select n_combinations from test_preregistrations where prereg_id = 'PR-TEST') = 3, 'n_combinations';
  assert (select n_trials_total from v_trial_count) >= 3, 'v_trial_count';
end $$;

insert into backtest_runs (run_id, prereg_id, kind, code_commit, data_hashes, n_trials_total, verdict, holdout_used, report, created_by_agent_id)
values ('RUN-1', 'PR-TEST', 'HARD_TEST', 'abc', '{}', 3, 'PASS', true, '{"oos": {"n": 50}}', 'claude');
-- La reserva final no se puede volver a usar.
select pg_temp.expect_error($$insert into backtest_runs (run_id, prereg_id, kind, code_commit, data_hashes, n_trials_total, verdict, holdout_used, report, created_by_agent_id)
  values ('RUN-2', 'PR-TEST', 'RETEST', 'abc', '{}', 3, 'PASS', true, '{}', 'claude')$$, 'ya se usó');

insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
values ('S-TEST', 'PAPER', 'pasó el hard test', 'claude', 'claude');
-- Solo el usuario promueve a LIVE_ELIGIBLE.
select pg_temp.expect_error($$insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
  values ('S-TEST', 'LIVE_ELIGIBLE', 'x', 'claude', 'claude')$$, 'Solo el usuario');
insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
values ('S-TEST', 'LIVE_ELIGIBLE', 'aprobado por el usuario', 'user', 'claude');

do $$ begin
  assert (select status from v_strategy_board where strategy_id = 'S-TEST') = 'LIVE_ELIGIBLE', 'tablero';
  assert (select last_run_id from v_strategy_board where strategy_id = 'S-TEST') = 'RUN-1', 'último run';
end $$;

-- Política "solo validadas": con una estrategia LIVE_ELIGIBLE, toda compra debe apoyarse en ella.
insert into risk_limits (max_position_usdt, max_open_positions, universe, executor_agent_id, set_by, note)
select 7, 1, array['BTCUSDT'], null, 'user', 'test' where not exists (select 1 from risk_limits);
select pg_temp.expect_error($$insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high,
  invalidation, targets, notional_usdt, thesis, cancel_conditions, expires_at)
  values ('P-NOSTRAT', 'claude', 'BTCUSDT', 'BUY', 100, 101, 95, '{110}', 7, 't', 't', now() + interval '1 hour')$$,
  'debe indicar strategy_id');
insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high, invalidation, targets,
  notional_usdt, thesis, cancel_conditions, expires_at, strategy_id)
values ('P-STRAT', 'claude', 'BTCUSDT', 'BUY', 100, 101, 95, '{110}', 7, 't', 't', now() + interval '1 hour', 'S-TEST');

-- Retirar es posible desde cualquier estado, y después ya no hay vuelta.
insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
values ('S-TEST', 'RETIRED', 'fin', 'user', 'claude');
select pg_temp.expect_error($$insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id)
  values ('S-TEST', 'RETIRED', 'x', 'user', 'claude')$$, 'retirada');

select pg_temp.expect_error($$update strategies set name = 'x'$$, 'append-only');

set local role anon;
select pg_temp.expect_error($$select * from v_strategy_board$$, 'permission denied');
reset role;

create table public.zz_strategy_test_reached_end (ok boolean);
select 'strategy_pipeline_test: OK' as result;
rollback;
