-- Equipo humano (pedido del usuario, 2026-09-27): registro de las personas que se suman a la startup, su rol, sus
-- accesos y su avance en el onboarding. Mismas reglas que el resto del diario: append-only, created_at lo pone la
-- base, sin acceso público. El estado vigente (rol, accesos, pasos hechos) sale de vistas sobre los eventos.
--
-- El fundador es "el usuario" de AGENTS.md y no es una fila de esta tabla: autorizar o vetar operaciones, fijar
-- límites de riesgo y declarar una estrategia LIVE_ELIGIBLE siguen siendo solo suyos. Por eso la base rechaza
-- conceder a un miembro cualquier acceso a Binance, escritura en el diario o permisos de decisión (journal:*).
-- Cambiar eso exige otra migración revisada por el fundador.
--
-- Los datos personales (nombre) viven solo aquí, nunca en el repositorio, que es público.

create table public.team_members (
  id text primary key check (id ~ '^[a-z][a-z0-9_]{1,30}$'),   -- handle; el rol de base personal es team_<id>
  display_name text not null check (length(display_name) between 1 and 80),
  github_login text check (github_login ~ '^[A-Za-z0-9](-?[A-Za-z0-9]){0,38}$'),
  created_at timestamptz not null default now()
);

-- Accesos que ningún miembro puede recibir: la cuenta de Binance es de los agentes, el diario lo escriben los
-- agentes, y las decisiones (autorizar, vetar, límites, LIVE_ELIGIBLE) son del fundador.
create function public.team_resource_forbidden(p_resource text) returns boolean
language sql immutable set search_path = '' as $$
  select p_resource like 'binance:%'
      or p_resource like 'journal:%'
      or (p_resource like 'supabase:finance-tool:%' and p_resource <> 'supabase:finance-tool:read')
$$;

create table public.team_member_events (
  id bigint generated always as identity primary key,
  member_id text not null references public.team_members (id),
  kind text not null
    check (kind in ('JOINED', 'ROLE_SET', 'ACCESS_GRANTED', 'ACCESS_REVOKED', 'STEP_DONE', 'LEFT')),
  role text check (role in ('observer', 'analyst', 'developer')),
  resource text check (resource ~ '^[a-z][a-z0-9_]*(:[a-z0-9_.-]+)+$'),
  step_id text check (step_id ~ '^[a-z][a-z0-9-]*$'),
  -- Quién tomó la decisión. Sumar, cambiar de rol, conceder acceso o dar de baja lo decide el fundador ('user'); el
  -- agente o la persona que lo registra cita su mensaje en note. Retirar un acceso nunca se bloquea.
  decided_by text not null check (decided_by in ('user', 'member', 'claude', 'chatgpt')),
  note text not null check (length(note) between 1 and 1000),
  created_at timestamptz not null default now(),
  check ((kind = 'ROLE_SET') = (role is not null)),
  check ((kind in ('ACCESS_GRANTED', 'ACCESS_REVOKED')) = (resource is not null)),
  check ((kind = 'STEP_DONE') = (step_id is not null)),
  check (kind not in ('JOINED', 'ROLE_SET', 'ACCESS_GRANTED', 'LEFT') or decided_by = 'user'),
  check (kind <> 'ACCESS_GRANTED' or not public.team_resource_forbidden(resource))
);

create index team_member_events_member on public.team_member_events (member_id, id desc);

do $$
declare
  t text;
begin
  foreach t in array array['team_members', 'team_member_events'] loop
    execute format('create trigger a_stamp_created_at before insert on public.%I for each row execute function public.stamp_created_at()', t);
    execute format('create trigger append_only before update or delete on public.%I for each row execute function public.forbid_mutation()', t);
    execute format('create trigger append_only_truncate before truncate on public.%I for each statement execute function public.forbid_mutation()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to dashboard_reader', t);
    execute format('create policy dashboard_read on public.%I for select to dashboard_reader using (true)', t);
  end loop;
end $$;

-- Una persona está activa si su último JOINED es posterior a su último LEFT (puede volver).
create view public.v_team_roster with (security_invoker = true) as
select m.id as member_id, m.display_name, m.github_login,
       last_join.created_at as joined_at,
       (last_join.id is not null and (last_left.id is null or last_left.id < last_join.id)) as active,
       last_role.role,
       (select count(distinct e.step_id) from public.team_member_events e
         where e.member_id = m.id and e.kind = 'STEP_DONE') as steps_done
from public.team_members m
left join lateral (select e.id, e.created_at from public.team_member_events e
                   where e.member_id = m.id and e.kind = 'JOINED' order by e.id desc limit 1) last_join on true
left join lateral (select e.id from public.team_member_events e
                   where e.member_id = m.id and e.kind = 'LEFT' order by e.id desc limit 1) last_left on true
left join lateral (select e.role from public.team_member_events e
                   where e.member_id = m.id and e.kind = 'ROLE_SET' order by e.id desc limit 1) last_role on true;

-- Accesos vigentes: el último evento de cada (persona, recurso) es un ACCESS_GRANTED.
create view public.v_team_access with (security_invoker = true) as
select last_event.member_id, last_event.resource, last_event.created_at as granted_at, r.active as member_active
from (
  select distinct on (e.member_id, e.resource) e.member_id, e.resource, e.kind, e.created_at
  from public.team_member_events e
  where e.kind in ('ACCESS_GRANTED', 'ACCESS_REVOKED')
  order by e.member_id, e.resource, e.id desc
) last_event
join public.v_team_roster r on r.member_id = last_event.member_id
where last_event.kind = 'ACCESS_GRANTED';

-- Offboarding: accesos que siguen concedidos a alguien que ya no está activo. Debe quedar vacía.
create view public.v_team_offboarding_pending with (security_invoker = true) as
select member_id, resource, granted_at from public.v_team_access where not member_active;

do $$
declare
  v text;
begin
  foreach v in array array['v_team_roster', 'v_team_access', 'v_team_offboarding_pending'] loop
    execute format('revoke all on public.%I from anon, authenticated', v);
    execute format('grant select on public.%I to dashboard_reader', v);
  end loop;
end $$;
