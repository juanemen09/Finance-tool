-- Equipo humano: append-only, accesos prohibidos, estado vigente desde eventos, offboarding y rol personal de lectura.
-- Transacción revertida: no deja rastro.
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

create function pg_temp.assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if ok is not true then raise exception 'Falla: %', msg; end if;
end $$;

insert into team_members (id, display_name, github_login) values ('primo_a', 'Primo A', 'primo-a');
insert into team_member_events (member_id, kind, decided_by, note) values ('primo_a', 'JOINED', 'user', 'autorizo');
insert into team_member_events (member_id, kind, role, decided_by, note)
values ('primo_a', 'ROLE_SET', 'analyst', 'user', 'analista');
insert into team_member_events (member_id, kind, resource, decided_by, note)
values ('primo_a', 'ACCESS_GRANTED', 'github:finance-tool:read', 'user', 'x'),
       ('primo_a', 'ACCESS_GRANTED', 'supabase:finance-tool:read', 'user', 'x'),
       ('primo_a', 'ACCESS_GRANTED', 'dashboard:finance-tool', 'user', 'x');
insert into team_member_events (member_id, kind, step_id, decided_by, note)
values ('primo_a', 'STEP_DONE', 'entorno-local', 'member', 'hecho'),
       ('primo_a', 'STEP_DONE', 'entorno-local', 'claude', 'repetido: cuenta una vez');

select pg_temp.assert((select role = 'analyst' and active and steps_done = 1 from v_team_roster where member_id = 'primo_a'),
                      'roster: rol, activo y pasos distintos');
select pg_temp.assert((select count(*) = 3 from v_team_access where member_id = 'primo_a'), 'tres accesos vigentes');

-- Retirar un acceso lo quita de los vigentes; retirar no exige al fundador.
insert into team_member_events (member_id, kind, resource, decided_by, note)
values ('primo_a', 'ACCESS_REVOKED', 'dashboard:finance-tool', 'claude', 'retirado');
select pg_temp.assert((select count(*) = 2 from v_team_access where member_id = 'primo_a'), 'revocado ya no vigente');

-- Decisiones del fundador: un agente o la persona no pueden sumarse, cambiar de rol ni concederse accesos.
select pg_temp.expect_error($$insert into team_member_events (member_id, kind, decided_by, note)
  values ('primo_a', 'JOINED', 'claude', 'x')$$, 'check constraint');
select pg_temp.expect_error($$insert into team_member_events (member_id, kind, role, decided_by, note)
  values ('primo_a', 'ROLE_SET', 'developer', 'member', 'x')$$, 'check constraint');
select pg_temp.expect_error($$insert into team_member_events (member_id, kind, resource, decided_by, note)
  values ('primo_a', 'ACCESS_GRANTED', 'github:praxiguard:write', 'chatgpt', 'x')$$, 'check constraint');

-- Accesos prohibidos incluso con decisión del fundador: Binance, escritura en el diario, decisiones.
select pg_temp.expect_error(format($$insert into team_member_events (member_id, kind, resource, decided_by, note)
  values ('primo_a', 'ACCESS_GRANTED', %L, 'user', 'x')$$, r), 'check constraint')
from unnest(array['binance:read', 'binance:trading', 'journal:authorize', 'journal:veto',
                  'supabase:finance-tool:write', 'supabase:finance-tool:service_role']) r;
-- Retirar un acceso prohibido sí se puede (limpieza).
insert into team_member_events (member_id, kind, resource, decided_by, note)
values ('primo_a', 'ACCESS_REVOKED', 'binance:read', 'user', 'limpieza');

-- Coherencia de columnas y roles válidos (el fundador no es un rol de la tabla).
select pg_temp.expect_error($$insert into team_member_events (member_id, kind, decided_by, note)
  values ('primo_a', 'ROLE_SET', 'user', 'sin rol')$$, 'check constraint');
select pg_temp.expect_error($$insert into team_member_events (member_id, kind, role, decided_by, note)
  values ('primo_a', 'ROLE_SET', 'founder', 'user', 'x')$$, 'check constraint');
select pg_temp.expect_error($$insert into team_member_events (member_id, kind, step_id, decided_by, note)
  values ('primo_a', 'STEP_DONE', 'Paso Raro', 'member', 'x')$$, 'check constraint');
select pg_temp.expect_error($$insert into team_members (id, display_name) values ('Mayus', 'x')$$, 'check constraint');

-- Append-only.
select pg_temp.expect_error($$update team_members set display_name = 'otro' where id = 'primo_a'$$, 'append-only');
select pg_temp.expect_error($$delete from team_member_events where member_id = 'primo_a'$$, 'append-only');

-- Baja: deja de estar activo y sus accesos aparecen como pendientes de retirar hasta revocarlos.
insert into team_member_events (member_id, kind, decided_by, note) values ('primo_a', 'LEFT', 'user', 'baja');
select pg_temp.assert((select not active from v_team_roster where member_id = 'primo_a'), 'baja: inactivo');
select pg_temp.assert((select count(*) = 2 from v_team_offboarding_pending where member_id = 'primo_a'),
                      'baja: dos accesos por retirar');
insert into team_member_events (member_id, kind, resource, decided_by, note)
select 'primo_a', 'ACCESS_REVOKED', resource, 'claude', 'offboarding'
from v_team_offboarding_pending where member_id = 'primo_a';
select pg_temp.assert((select count(*) = 0 from v_team_offboarding_pending), 'offboarding completo');

-- Vuelve: un JOINED posterior lo reactiva.
insert into team_member_events (member_id, kind, decided_by, note) values ('primo_a', 'JOINED', 'user', 'vuelve');
select pg_temp.assert((select active from v_team_roster where member_id = 'primo_a'), 'reingreso: activo');

-- Rol personal de lectura (lo que genera `python -m team sql join`): hereda dashboard_reader, lee y no escribe.
create role team_primo_a nologin in role dashboard_reader;
alter role team_primo_a set default_transaction_read_only = on;
grant team_primo_a to current_user with set true;
set local role team_primo_a;
select pg_temp.assert((select count(*) >= 1 from v_team_roster), 'lectura del equipo');
select pg_temp.assert((select count(*) >= 0 from risk_limits), 'lectura del diario');
select pg_temp.expect_error($$insert into team_member_events (member_id, kind, step_id, decided_by, note)
  values ('primo_a', 'STEP_DONE', 'pruebas', 'member', 'x')$$, 'permission denied');
select pg_temp.expect_error($$insert into agent_messages (from_agent_id, to_agent_id, kind, body, expires_at)
  values ('claude', 'chatgpt', 'INFO', 'x', now() + interval '1 hour')$$, 'permission denied');
reset role;

-- Sin acceso público.
select pg_temp.assert(not has_table_privilege('anon', 'public.team_members', 'select'), 'anon no lee');
select pg_temp.assert(not has_table_privilege('authenticated', 'public.v_team_roster', 'select'), 'authenticated no lee');

rollback;
