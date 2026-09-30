-- Pronósticos en papel: append-only, solo filas de Claude, lectura del panel y cálculo del skill. Transacción revertida.
begin;

-- postgres administra los roles pero no puede asumirlos (PG16): se le da SET solo dentro de esta transacción.
grant lab_ingest, dashboard_reader to current_user with set true;

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

set local role lab_ingest;
insert into forecasts (model, symbol, horizon_days, origin_close_time, target_close_time, last_close, quantiles, benchmark, recorded_by_agent_id)
values ('test-model', 'BTCUSDT', 7, '2099-01-01', '2099-01-08', 100, '{"p50": 101}', '{"p50": 100}', 'claude'),
       ('test-model', 'BTCUSDT', 7, '2099-01-01', '2099-01-08', 100, '{"p50": 999}', '{"p50": 100}', 'claude')
on conflict do nothing;
select pg_temp.expect_error($$select count(*) from forecasts$$, 'permission denied');
reset role;

select pg_temp.expect_error($$update forecasts set last_close = 1 where model = 'test-model'$$, 'append-only');
select pg_temp.expect_error($$insert into forecasts (model, symbol, horizon_days, origin_close_time, target_close_time, last_close, quantiles, benchmark, recorded_by_agent_id)
  values ('test-model', 'DOGEUSDT', 1, now(), now() + interval '1 day', 1, '{}', '{}', 'claude')$$, 'check');

insert into forecast_outcomes (forecast_id, realized_close, pinball_model, pinball_benchmark, direction_hit, inside_p10_p90, recorded_by_agent_id)
select id, 102, 0.01, 0.02, true, true, 'claude' from forecasts where model = 'test-model';

set local role dashboard_reader;
do $$ begin
  assert (select count(*) from forecasts where model = 'test-model') = 1, 'el duplicado no entra';
  assert (select (quantiles ->> 'p50')::numeric from forecasts where model = 'test-model') = 101, 'gana la primera fila';
  assert (select skill_vs_random_walk from v_forecast_skill where model = 'test-model' and symbol is null and horizon_days = 7) = 0.5,
    'skill a 7 días sumando activos = 1 - 0.01 / 0.02';
  assert (select median_return from v_forecast_latest where model = 'test-model') = 0.01, 'retorno de la mediana';
end $$;
reset role;

do $$ begin
  assert not has_table_privilege('anon', 'public.forecasts', 'select'), 'anon no debe leer';
end $$;

select 'forecasts_test OK' as resultado;
rollback;
