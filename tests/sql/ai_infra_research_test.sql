-- Tablas de la tesis de IA: append-only, sin duplicados, lectura del panel e inserción limitada del recolector.
-- Transacción revertida: no deja rastro.
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
insert into agents (id, display_name, role) select 'chatgpt', 'ChatGPT', 'execution'
where not exists (select 1 from agents where id = 'chatgpt');

set local role lab_ingest;
insert into research_facts (fact_key, topic, metric, entity, period_end, value, unit, source_url, recorded_by_agent_id)
values ('test:capex:MSFT:2099-06-30', 'ai_demand', 'capex_quarter_usd', 'MSFT', '2099-06-30', 1e9, 'USD',
        'https://data.sec.gov/x', 'claude') on conflict do nothing;
insert into research_facts (fact_key, topic, metric, entity, period_end, value, unit, source_url, recorded_by_agent_id)
values ('test:capex:MSFT:2099-06-30', 'ai_demand', 'capex_quarter_usd', 'MSFT', '2099-06-30', 2e9, 'USD',
        'https://data.sec.gov/x', 'claude') on conflict do nothing;
insert into research_reports (report_key, kind, as_of, title, body, data, recorded_by_agent_id)
values ('AI_DEMAND:test', 'AI_DEMAND', '2099-06-30', 't', 'b', '{"headline": {"x": 1}}', 'claude');
select pg_temp.expect_error($$select count(*) from research_facts$$, 'permission denied');
select pg_temp.expect_error($$insert into research_reports (report_key, kind, as_of, title, body, recorded_by_agent_id)
  values ('k2', 'AI_BOTTLENECK', '2099-06-30', 't', 'b', 'chatgpt')$$, 'row-level security');
reset role;

select pg_temp.expect_error($$update research_facts set value = 0 where fact_key like 'test:%'$$, 'append-only');
select pg_temp.expect_error($$delete from research_reports where report_key = 'AI_DEMAND:test'$$, 'append-only');
select pg_temp.expect_error($$insert into research_facts (fact_key, topic, metric, entity, period_end, unit, source_url, recorded_by_agent_id)
  values ('k3', 'crypto', 'm', 'E', '2099-01-01', 'USD', 'https://x', 'claude')$$, 'check');
select pg_temp.expect_error($$insert into research_facts (fact_key, topic, metric, entity, period_end, unit, source_url, recorded_by_agent_id)
  values ('k4', '13f', 'm', 'E', '2099-01-01', 'USD', 'http://x', 'claude')$$, 'check');

set local role dashboard_reader;
do $$ begin
  assert (select value from research_facts where fact_key = 'test:capex:MSFT:2099-06-30') = 1e9, 'el duplicado no debe entrar';
  assert (select title from v_research_latest where kind = 'AI_DEMAND') is not null, 'el panel ve el último informe';
end $$;
reset role;

do $$ begin
  assert not has_table_privilege('anon', 'public.research_facts', 'select'), 'anon no debe leer';
  assert not has_table_privilege('anon', 'public.v_research_latest', 'select'), 'anon no debe leer la vista';
  assert not has_table_privilege('lab_ingest', 'public.research_reports', 'update'), 'el recolector no modifica';
end $$;

select 'ai_infra_research_test OK' as resultado;
rollback;
