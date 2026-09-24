-- Pruebas de la autorización permanente con ventana de veto. Transacción revertida.
begin;

insert into agents (id, display_name, role) select v.id, v.id, 'test'
from (values ('claude'), ('chatgpt')) as v(id) where not exists (select 1 from agents a where a.id = v.id);
insert into risk_limits (max_position_usdt, max_open_positions, universe, executor_agent_id, set_by, note)
values (7, 1, array['BTCUSDT'], 'chatgpt', 'user', 'test');

-- Estrategia validada de punta a punta.
insert into strategies (strategy_id, name, family, economic_rationale, rules_spec, applicability, created_by_agent_id)
values ('S-OK', 'ok', 'trend', 'r', '{}', '{}', 'claude');
insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id) values
  ('S-OK', 'DISCOVERED', 'x', 'claude', 'claude'), ('S-OK', 'CANDIDATE', 'x', 'claude', 'claude'),
  ('S-OK', 'PREREGISTERED', 'x', 'claude', 'claude'), ('S-OK', 'TESTING', 'x', 'claude', 'claude');
insert into test_preregistrations (prereg_id, strategy_id, hypothesis, param_grid, symbols, bar_interval, holdout_bars,
  train_bars, test_bars, costs, thresholds, code_commit, created_by_agent_id)
values ('PR-OK', 'S-OK', 'h', '[{}]', '{BTCUSDT}', '1h', 1, 1, 1, '{}', '{}', 'abc', 'claude');
insert into backtest_runs (run_id, prereg_id, kind, code_commit, data_hashes, n_trials_total, verdict, holdout_used, report, created_by_agent_id)
values ('RUN-OK', 'PR-OK', 'HARD_TEST', 'abc', '{}', 1, 'PASS', true, '{}', 'claude');
insert into strategy_status_events (strategy_id, status, reason, decided_by, recorded_by_agent_id) values
  ('S-OK', 'PAPER', 'x', 'claude', 'claude'), ('S-OK', 'LIVE_ELIGIBLE', 'x', 'user', 'claude');

insert into standing_authorizations (set_by, active, veto_minutes, max_loss_usdt, min_reward_risk, weekly_loss_limit_usdt,
  user_message_quote, recorded_by_agent_id)
values ('user', true, 15, 0.25, 1.5, 1.0, 'test', 'claude');

-- Pérdida estimada: 7*(100-98)/100 + 7*2*0.0015 = 0.161 USDT; relación 4/2 = 2.
insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high, invalidation, targets,
  notional_usdt, thesis, cancel_conditions, expires_at, strategy_id) values
  ('P-OK', 'claude', 'BTCUSDT', 'BUY', 99.5, 100, 98, '{104}', 7, 't', 't', now() + interval '2 hours', 'S-OK'),
  ('P-BIGSTOP', 'claude', 'BTCUSDT', 'BUY', 99.5, 100, 90, '{120}', 7, 't', 't', now() + interval '2 hours', 'S-OK'),
  ('P-LOWRR', 'claude', 'BTCUSDT', 'BUY', 99.5, 100, 98, '{101}', 7, 't', 't', now() + interval '2 hours', 'S-OK');
insert into risk_reviews (review_id, proposal_id, reviewer_agent_id, verdict, market_data_as_of, reasoning)
select 'R-' || proposal_id, proposal_id, 'chatgpt', 'APPROVE', now(), 'ok' from trade_proposals where proposal_id like 'P-%';

create temp table t_at as select now() + interval '16 minutes' as later;

do $$
declare
  later timestamptz := (select later from t_at);
  s jsonb;
begin
  -- Dentro de la ventana de veto: todavía no.
  s := auto_authorization_status('P-OK', now());
  assert (s ->> 'veto_window_elapsed')::boolean = false and (s ->> 'auto_ok')::boolean = false, 'ventana: ' || s::text;
  assert not exists (select 1 from v_executable_proposals where proposal_id = 'P-OK'), 'no debe ser ejecutable aún';

  -- Pasada la ventana: sí, y la pérdida y la relación se calculan bien.
  s := auto_authorization_status('P-OK', later);
  assert (s ->> 'auto_ok')::boolean, 'debería autorizarse: ' || s::text;
  assert (s ->> 'estimated_max_loss_usdt')::numeric = 0.161, 'pérdida estimada: ' || s::text;
  assert (s ->> 'reward_risk')::numeric = 2, 'relación: ' || s::text;

  -- Stop demasiado lejos o relación insuficiente: no.
  s := auto_authorization_status('P-BIGSTOP', later);
  assert (s ->> 'max_loss_ok')::boolean = false and (s ->> 'auto_ok')::boolean = false, 'stop lejano: ' || s::text;
  s := auto_authorization_status('P-LOWRR', later);
  assert (s ->> 'reward_risk_ok')::boolean = false and (s ->> 'auto_ok')::boolean = false, 'relación baja: ' || s::text;
end $$;

-- Permisos del ejecutor sin corregir: bloquea la autorización automática.
insert into events (agent_id, kind, severity, message) values ('claude', 'permissions_review', 'warning', 'x');
do $$ begin
  assert (auto_authorization_status('P-OK', (select later from t_at)) ->> 'executor_permissions_ok')::boolean = false,
    'permisos pendientes deben bloquear';
end $$;
insert into events (agent_id, kind, severity, message, resolves_event_id)
select 'claude', 'resolution', 'info', 'resuelto', id from events where kind = 'permissions_review';

-- Veto del usuario: bloquea.
insert into user_vetoes (proposal_id, user_message_quote, recorded_by_agent_id) values ('P-OK', 'veto P-OK', 'chatgpt');
do $$ begin
  assert (auto_authorization_status('P-OK', (select later from t_at)) ->> 'auto_ok')::boolean = false, 'veto';
end $$;

-- Autorización explícita del usuario: ejecutable ya, en modo USER, aunque no haya pasado la ventana.
insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high, invalidation, targets,
  notional_usdt, thesis, cancel_conditions, expires_at, strategy_id)
values ('P-USER', 'claude', 'BTCUSDT', 'BUY', 99.5, 100, 98, '{104}', 7, 't', 't', now() + interval '2 hours', 'S-OK');
insert into risk_reviews (review_id, proposal_id, reviewer_agent_id, verdict, market_data_as_of, reasoning)
values ('R-P-USER', 'P-USER', 'chatgpt', 'APPROVE', now(), 'ok');
insert into execution_authorizations (proposal_id, authorized_by, recorded_by_agent_id, user_message_quote)
values ('P-USER', 'user', 'chatgpt', 'autorizo P-USER');
do $$ begin
  assert (select authorization_mode from v_executable_proposals where proposal_id = 'P-USER') = 'USER', 'modo USER';
end $$;

-- Límite semanal: una pérdida de 1,2 USDT esta semana suspende la autorización automática.
insert into trades (trade_ref, proposal_id, executor_agent_id, symbol, side, executed_at, entry_price, quantity,
  notional_usdt, fee_amount, fee_asset, fee_usdt, binance_order_ids, market_regime, entry_thesis, invalidation, stop, targets)
values ('Trade #950', 'P-USER', 'chatgpt', 'BTCUSDT', 'BUY', now(), 100, 0.07, 7, 0, 'USDT', 0.007, '{1}', 'x', 'x', 98, 98, '{104}');
insert into trade_closures (trade_ref, recorded_by_agent_id, closed_at, exit_reason, exit_price, quantity, fee_amount,
  fee_asset, fee_usdt, binance_order_ids, pnl_usdt, pnl_pct, went_right, went_wrong, lessons)
values ('Trade #950', 'chatgpt', now(), 'STOP', 83, 0.07, 0, 'USDT', 0, '{2}', -1.2, -17, 'x', 'x', 'x');
insert into trade_proposals (proposal_id, agent_id, symbol, side, entry_low, entry_high, invalidation, targets,
  notional_usdt, thesis, cancel_conditions, expires_at, strategy_id)
values ('P-AFTERLOSS', 'claude', 'BTCUSDT', 'BUY', 99.5, 100, 98, '{104}', 7, 't', 't', now() + interval '2 hours', 'S-OK');
insert into risk_reviews (review_id, proposal_id, reviewer_agent_id, verdict, market_data_as_of, reasoning)
values ('R-AFTERLOSS', 'P-AFTERLOSS', 'chatgpt', 'APPROVE', now(), 'ok');
do $$ begin
  assert (auto_authorization_status('P-AFTERLOSS', (select later from t_at)) ->> 'weekly_loss_ok')::boolean = false,
    'límite semanal';
end $$;

select 'standing_authorization_test: OK' as result;
rollback;
