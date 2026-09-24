-- Pipeline de estrategias: fuentes -> estrategias formalizadas -> pre-registro -> hard test -> papel -> uso.
-- Mismas reglas que el resto del diario: append-only, created_at lo pone la base, sin acceso público.

create table public.strategy_sources (
  id bigint generated always as identity primary key,
  source_key text not null unique,            -- p. ej. 'arxiv:2608.01234', 'quantpedia:<slug>'
  source text not null check (source in ('arxiv', 'quantpedia', 'ssrn', 'journal', 'other')),
  url text not null,
  title text not null,
  authors text[] not null default '{}',
  published_at date,
  submitted_by text not null,                 -- agent_id o 'user' (entradas manuales)
  own_summary text not null,                  -- resumen propio; nunca el texto original
  created_at timestamptz not null default now()
);

create table public.strategies (
  id bigint generated always as identity primary key,
  strategy_id text not null unique,
  source_key text references public.strategy_sources (source_key),
  name text not null,
  family text not null,
  economic_rationale text not null,           -- por qué debería existir el edge
  rules_spec jsonb not null,                  -- reglas formalizadas, sin ambigüedad
  implementation_ref text,                    -- módulo:función en el repo, cuando exista
  applicability jsonb not null,               -- encaje con Spot, 5 pares, 1h/4h, 7 USDT, costes
  created_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

create table public.strategy_status_events (
  id bigint generated always as identity primary key,
  strategy_id text not null references public.strategies (strategy_id),
  status text not null check (status in ('DISCOVERED', 'NOT_APPLICABLE', 'CANDIDATE', 'PREREGISTERED', 'TESTING',
                                         'REJECTED', 'PAPER', 'LIVE_ELIGIBLE', 'DEGRADED', 'RETIRED')),
  reason text not null,
  evidence jsonb not null default '{}',
  decided_by text not null,                   -- agent_id o 'user'
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

create table public.test_preregistrations (
  id bigint generated always as identity primary key,
  prereg_id text not null unique,
  strategy_id text not null references public.strategies (strategy_id),
  hypothesis text not null,
  param_grid jsonb not null check (jsonb_typeof(param_grid) = 'array' and jsonb_array_length(param_grid) > 0),
  n_combinations integer generated always as (jsonb_array_length(param_grid)) stored,
  symbols text[] not null,
  bar_interval text not null,
  holdout_bars integer not null check (holdout_bars > 0),
  train_bars integer not null check (train_bars > 0),
  test_bars integer not null check (test_bars > 0),
  costs jsonb not null,
  thresholds jsonb not null,
  code_commit text not null,
  created_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

create table public.backtest_runs (
  id bigint generated always as identity primary key,
  run_id text not null unique,
  prereg_id text not null references public.test_preregistrations (prereg_id),
  kind text not null check (kind in ('HARD_TEST', 'PAPER_REVIEW', 'RETEST')),
  code_commit text not null,
  data_hashes jsonb not null,
  n_trials_total integer not null check (n_trials_total > 0),
  verdict text not null check (verdict in ('PASS', 'FAIL')),
  holdout_used boolean not null,
  report jsonb not null,
  created_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

-- Qué dice ahora cada estrategia en papel o en uso; lo escriben los ciclos de 4h.
create table public.strategy_signals (
  id bigint generated always as identity primary key,
  strategy_id text not null references public.strategies (strategy_id),
  cycle_id text not null,
  symbol text not null,
  signal text not null check (signal in ('ENTRY', 'NONE')),
  entry_price numeric,
  stop numeric,
  target numeric,
  bar_close_time timestamptz not null,
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now(),
  unique (strategy_id, cycle_id, symbol)
);

-- ---------------------------------------------------------------------------
-- Reglas
-- ---------------------------------------------------------------------------

create function public.latest_strategy_status(p_strategy_id text) returns text
language sql stable set search_path = '' as $$
  select status from public.strategy_status_events where strategy_id = p_strategy_id order by id desc limit 1
$$;

create function public.check_strategy_transition() returns trigger
language plpgsql set search_path = '' as $$
declare
  current_status text := public.latest_strategy_status(new.strategy_id);
  allowed text[];
begin
  if new.decided_by <> 'user' and not exists (select 1 from public.agents where id = new.decided_by) then
    raise exception 'decided_by debe ser un agent_id o ''user'' (recibido %)', new.decided_by;
  end if;
  allowed := case coalesce(current_status, '')
    when '' then array['DISCOVERED']
    when 'DISCOVERED' then array['CANDIDATE', 'NOT_APPLICABLE']
    when 'NOT_APPLICABLE' then array['CANDIDATE']
    when 'CANDIDATE' then array['PREREGISTERED', 'NOT_APPLICABLE']
    when 'PREREGISTERED' then array['TESTING']
    when 'TESTING' then array['REJECTED', 'PAPER']
    when 'REJECTED' then array['PREREGISTERED']
    when 'PAPER' then array['LIVE_ELIGIBLE', 'REJECTED', 'DEGRADED']
    when 'LIVE_ELIGIBLE' then array['DEGRADED']
    when 'DEGRADED' then array['PAPER', 'REJECTED']
    else array[]::text[]
  end;
  if new.status <> 'RETIRED' and not (new.status = any (allowed)) then
    raise exception 'Transición no permitida: % -> % (permitidas: %)', coalesce(current_status, 'nada'), new.status, allowed;
  end if;
  if current_status = 'RETIRED' then
    raise exception 'La estrategia % está retirada', new.strategy_id;
  end if;
  if new.status = 'LIVE_ELIGIBLE' and new.decided_by <> 'user' then
    raise exception 'Solo el usuario puede marcar una estrategia como LIVE_ELIGIBLE';
  end if;
  if new.status = 'PAPER' and current_status = 'TESTING' and not exists (
    select 1 from public.backtest_runs r join public.test_preregistrations p using (prereg_id)
    where p.strategy_id = new.strategy_id and r.kind = 'HARD_TEST' and r.verdict = 'PASS'
  ) then
    raise exception 'PAPER exige un HARD_TEST con veredicto PASS para %', new.strategy_id;
  end if;
  return new;
end $$;

-- La reserva final se usa una sola vez por estrategia: mirarla dos veces la convierte en datos de desarrollo.
create function public.check_backtest_run() returns trigger
language plpgsql set search_path = '' as $$
declare
  sid text;
begin
  select strategy_id into sid from public.test_preregistrations where prereg_id = new.prereg_id;
  if new.holdout_used and exists (
    select 1 from public.backtest_runs r join public.test_preregistrations p using (prereg_id)
    where p.strategy_id = sid and r.holdout_used
  ) then
    raise exception 'La reserva final de % ya se usó; no se puede volver a evaluar', sid;
  end if;
  return new;
end $$;

do $$
declare
  t text;
begin
  foreach t in array array['strategy_sources', 'strategies', 'strategy_status_events', 'test_preregistrations',
                           'backtest_runs', 'strategy_signals'] loop
    execute format('create trigger a_stamp_created_at before insert on public.%I for each row execute function public.stamp_created_at()', t);
    execute format('create trigger append_only before update or delete on public.%I for each row execute function public.forbid_mutation()', t);
    execute format('create trigger append_only_truncate before truncate on public.%I for each statement execute function public.forbid_mutation()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;

create trigger b_check_strategy_transition before insert on public.strategy_status_events
  for each row execute function public.check_strategy_transition();
create trigger b_check_backtest_run before insert on public.backtest_runs
  for each row execute function public.check_backtest_run();

create index strategy_status_events_strategy_idx on public.strategy_status_events (strategy_id, id desc);
create index test_preregistrations_strategy_idx on public.test_preregistrations (strategy_id);

-- ---------------------------------------------------------------------------
-- Vistas
-- ---------------------------------------------------------------------------

-- Total de combinaciones probadas en todo el laboratorio: el N del Deflated Sharpe.
create view public.v_trial_count with (security_invoker = true) as
select coalesce(sum(n_combinations), 0)::integer as n_trials_total, count(*) as preregistrations
from public.test_preregistrations;

create view public.v_strategy_board with (security_invoker = true) as
select
  s.strategy_id,
  s.name,
  s.family,
  s.source_key,
  st.status,
  st.reason as status_reason,
  st.created_at as status_since,
  lr.run_id as last_run_id,
  lr.kind as last_run_kind,
  lr.verdict as last_verdict,
  lr.report -> 'oos' as last_oos,
  lr.created_at as last_run_at
from public.strategies s
left join lateral (
  select e.status, e.reason, e.created_at from public.strategy_status_events e
  where e.strategy_id = s.strategy_id order by e.id desc limit 1
) st on true
left join lateral (
  select r.run_id, r.kind, r.verdict, r.report, r.created_at
  from public.backtest_runs r join public.test_preregistrations p using (prereg_id)
  where p.strategy_id = s.strategy_id order by r.id desc limit 1
) lr on true;

revoke all on public.v_trial_count from anon, authenticated;
revoke all on public.v_strategy_board from anon, authenticated;
