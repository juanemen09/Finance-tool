-- El rol del centro de mando lee todo y no puede cambiar nada. Transacción revertida: no deja rastro.
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
insert into events (agent_id, kind, severity, message) values ('claude', 'test', 'info', 'fila de prueba del lector');

set local role dashboard_reader;

do $$ begin
  assert (select count(*) from events where message = 'fila de prueba del lector') = 1,
    'el lector debe ver filas pese a RLS';
  assert (select count(*) from v_open_events where message = 'fila de prueba del lector') = 1,
    'el lector debe poder leer las vistas';
end $$;

select pg_temp.expect_error($$insert into events (agent_id, kind, severity, message) values ('claude', 'x', 'info', 'x')$$,
  'permission denied');
select pg_temp.expect_error($$insert into user_vetoes (proposal_id, user_message_quote, recorded_by_agent_id) values ('P-X', 'veto P-X', 'claude')$$,
  'permission denied');
select pg_temp.expect_error($$insert into execution_authorizations (proposal_id) values ('P-X')$$, 'permission denied');
select pg_temp.expect_error($$update events set message = 'x'$$, 'permission denied');
select pg_temp.expect_error($$delete from news_items$$, 'permission denied');
select pg_temp.expect_error($$create table public.intruso (id int)$$, 'permission denied');

reset role;

do $$ begin
  assert not exists (select 1 from pg_roles where rolname = 'dashboard_reader' and (rolsuper or rolcreaterole or rolcreatedb or rolbypassrls)),
    'el lector no debe tener privilegios especiales';
  assert (select count(*) from pg_policies where roles @> array['dashboard_reader'::name] and cmd <> 'SELECT') = 0,
    'solo políticas de lectura para el lector';
  assert not has_table_privilege('dashboard_reader', 'public.trade_proposals', 'insert'), 'sin insert';
end $$;

select 'dashboard_reader_test OK' as resultado;
rollback;
