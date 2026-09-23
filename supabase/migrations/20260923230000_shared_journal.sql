-- AI Trading Lab: diario compartido entre agentes (Claude = riesgo, ChatGPT/Codex = ejecución).
--
-- Principios:
--   * Append-only: todo se registra con INSERT. UPDATE/DELETE/TRUNCATE los bloquea un trigger,
--     así ningún agente puede reescribir la conclusión de otro. Corregir = insertar un registro nuevo.
--     No es una frontera de seguridad (un superusuario puede desactivar triggers); es una barrera
--     contra errores de agentes.
--   * created_at lo pone la base, no el agente: nadie puede fechar hacia atrás una decisión.
--   * El estado (posición abierta, eventos sin resolver, propuestas ejecutables) sale de vistas.
--   * Sin acceso para anon/authenticated: solo service_role / conectores MCP.

-- ---------------------------------------------------------------------------
-- Funciones de soporte
-- ---------------------------------------------------------------------------

create function public.forbid_mutation() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'AI Trading Lab es append-only: % sobre % no está permitido. Inserta un registro nuevo.',
    tg_op, tg_table_name;
end $$;

create function public.stamp_created_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.created_at := now();
  return new;
end $$;

-- Niveles coherentes para una compra spot: invalidación por debajo de la zona de entrada
-- y todos los objetivos por encima de ella.
create function public.validate_buy_levels(
  p_entry_low numeric, p_entry_high numeric, p_invalidation numeric, p_targets numeric[]
) returns void
language plpgsql immutable set search_path = '' as $$
begin
  if p_entry_low is null or p_entry_high is null or p_invalidation is null
     or p_targets is null or cardinality(p_targets) = 0 then
    raise exception 'Una compra requiere entry_low, entry_high, invalidation y al menos un target';
  end if;
  if p_entry_low > p_entry_high then
    raise exception 'entry_low (%) mayor que entry_high (%)', p_entry_low, p_entry_high;
  end if;
  if p_invalidation >= p_entry_low then
    raise exception 'La invalidación (%) debe estar por debajo de la zona de entrada (%)', p_invalidation, p_entry_low;
  end if;
  if (select min(t) from unnest(p_targets) as t) <= p_entry_high then
    raise exception 'Todos los targets deben estar por encima de la zona de entrada (%)', p_entry_high;
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- Tablas
-- ---------------------------------------------------------------------------

create table public.agents (
  id text primary key check (id ~ '^[a-z][a-z0-9_]*$'),
  display_name text not null,
  role text not null,
  created_at timestamptz not null default now()
);

-- La fila más reciente es la vigente. Solo el usuario fija límites; la base no puede autenticarlo,
-- así que set_by documenta quién decidió, y el agente que inserta debe citar la instrucción en note.
create table public.risk_limits (
  id bigint generated always as identity primary key,
  max_position_usdt numeric(12, 2) not null check (max_position_usdt > 0),
  max_open_positions integer not null check (max_open_positions >= 1),
  universe text[] not null check (cardinality(universe) > 0),
  executor_agent_id text references public.agents (id),
  set_by text not null check (set_by = 'user'),
  note text not null,
  created_at timestamptz not null default now()
);

create table public.analyses (
  id bigint generated always as identity primary key,
  analysis_id text not null unique,
  agent_id text not null references public.agents (id),
  cycle_id text,
  related_trade_id text check (related_trade_id ~ '^Trade #[0-9]{3,}$'),
  assets_analyzed text[] not null check (cardinality(assets_analyzed) > 0),
  timeframes text[] not null,
  market_data_as_of timestamptz not null,
  market_regime text not null,
  thesis text not null,
  supporting_evidence jsonb not null default '[]',
  counterarguments jsonb not null default '[]',
  risk_factors jsonb not null default '[]',
  proposed_action text not null
    check (proposed_action in ('BUY_CANDIDATE', 'HOLD', 'REDUCE', 'SELL_CANDIDATE', 'DO_NOTHING')),
  symbol text,
  entry_low numeric,
  entry_high numeric,
  invalidation numeric,
  targets numeric[],
  valid_until timestamptz,
  confidence_context text not null,
  status text not null default 'FINAL' check (status in ('FINAL', 'SUPERSEDED_BY_NEW_RECORD')),
  details jsonb not null default '{}',
  created_at timestamptz not null default now(),
  check (proposed_action <> 'BUY_CANDIDATE' or (symbol is not null and valid_until is not null))
);

create table public.trade_proposals (
  id bigint generated always as identity primary key,
  proposal_id text not null unique,
  agent_id text not null references public.agents (id),
  analysis_id text references public.analyses (analysis_id),
  symbol text not null,
  side text not null check (side in ('BUY', 'SELL')),
  entry_low numeric,
  entry_high numeric,
  invalidation numeric,
  targets numeric[],
  notional_usdt numeric(12, 2) not null check (notional_usdt > 0),
  rr_estimate numeric,
  thesis text not null,
  cancel_conditions text not null,
  expires_at timestamptz not null,
  details jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table public.risk_reviews (
  id bigint generated always as identity primary key,
  review_id text not null unique,
  proposal_id text not null references public.trade_proposals (proposal_id),
  reviewer_agent_id text not null references public.agents (id),
  verdict text not null check (verdict in ('APPROVE', 'WAIT', 'REJECT', 'NEEDS_REASSESSMENT')),
  market_data_as_of timestamptz not null,
  reasoning text not null,
  evidence jsonb not null default '{}',
  disagreement_note text,
  created_at timestamptz not null default now()
);

-- Autorización explícita del usuario para ejecutar una propuesta concreta.
create table public.execution_authorizations (
  id bigint generated always as identity primary key,
  proposal_id text not null references public.trade_proposals (proposal_id),
  authorized_by text not null check (authorized_by = 'user'),
  recorded_by_agent_id text not null references public.agents (id),
  user_message_quote text not null,
  created_at timestamptz not null default now()
);

create table public.trades (
  id bigint generated always as identity primary key,
  trade_ref text not null unique check (trade_ref ~ '^Trade #[0-9]{3,}$'),
  proposal_id text not null references public.trade_proposals (proposal_id),
  executor_agent_id text not null references public.agents (id),
  symbol text not null,
  side text not null check (side = 'BUY'),
  executed_at timestamptz not null,
  entry_price numeric not null check (entry_price > 0),
  quantity numeric not null check (quantity > 0),
  notional_usdt numeric not null check (notional_usdt > 0),
  fee_amount numeric not null check (fee_amount >= 0),
  fee_asset text not null,
  fee_usdt numeric not null check (fee_usdt >= 0),
  binance_order_ids text[] not null check (cardinality(binance_order_ids) > 0),
  market_regime text not null,
  entry_thesis text not null,
  invalidation numeric not null,
  stop numeric not null,
  targets numeric[] not null,
  -- Lo calcula el trigger: si la ejecución no pasó por el protocolo, el trade se registra igual
  -- (el diario nunca debe perder una operación real) pero queda marcado y genera un evento crítico.
  gate_passed boolean not null default false,
  gate_detail text,
  created_at timestamptz not null default now()
);

create table public.trade_closures (
  id bigint generated always as identity primary key,
  trade_ref text not null unique references public.trades (trade_ref),
  recorded_by_agent_id text not null references public.agents (id),
  closed_at timestamptz not null,
  exit_reason text not null check (exit_reason in ('STOP', 'TARGET', 'INVALIDATION', 'MANUAL', 'TIME')),
  exit_price numeric not null check (exit_price > 0),
  quantity numeric not null check (quantity > 0),
  fee_amount numeric not null check (fee_amount >= 0),
  fee_asset text not null,
  fee_usdt numeric not null check (fee_usdt >= 0),
  binance_order_ids text[] not null check (cardinality(binance_order_ids) > 0),
  pnl_usdt numeric not null,
  pnl_pct numeric not null,
  mfe_pct numeric,
  mae_pct numeric,
  went_right text not null,
  went_wrong text not null,
  lessons text not null,
  created_at timestamptz not null default now()
);

create table public.portfolio_snapshots (
  id bigint generated always as identity primary key,
  agent_id text not null references public.agents (id),
  source text not null,
  account_uid text not null,
  balances jsonb not null,
  open_orders jsonb not null,
  api_permissions jsonb,
  observed_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table public.events (
  id bigint generated always as identity primary key,
  agent_id text not null references public.agents (id),
  kind text not null,
  severity text not null check (severity in ('info', 'warning', 'critical')),
  message text not null,
  related_ref text,
  resolves_event_id bigint references public.events (id),
  created_at timestamptz not null default now()
);

-- Puntuación objetiva de decisiones con el precio posterior (competición a ciegas entre agentes).
create table public.decision_scores (
  id bigint generated always as identity primary key,
  analysis_id text not null references public.analyses (analysis_id),
  scorer_agent_id text not null references public.agents (id),
  scorer_version text not null,
  horizon_hours integer not null check (horizon_hours > 0),
  outcome text not null
    check (outcome in ('TARGET_HIT', 'STOP_HIT', 'NOT_FILLED', 'OPEN_AT_HORIZON', 'NO_TRADE')),
  fill_price numeric,
  exit_price numeric,
  r_multiple numeric,
  r_multiple_after_fees numeric,
  mfe_pct numeric,
  mae_pct numeric,
  details jsonb not null default '{}',
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Reglas de negocio
-- ---------------------------------------------------------------------------

create function public.check_analysis() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.proposed_action = 'BUY_CANDIDATE' then
    perform public.validate_buy_levels(new.entry_low, new.entry_high, new.invalidation, new.targets);
  end if;
  return new;
end $$;

create function public.check_proposal() returns trigger
language plpgsql set search_path = '' as $$
declare
  lim public.risk_limits;
begin
  select * into lim from public.risk_limits order by id desc limit 1;
  if lim.id is null then
    raise exception 'No hay risk_limits vigentes';
  end if;
  if not (new.symbol = any (lim.universe)) then
    raise exception '% está fuera del universo autorizado %', new.symbol, lim.universe;
  end if;
  if new.side = 'BUY' then
    if new.notional_usdt > lim.max_position_usdt then
      raise exception 'Notional % USDT supera el máximo por posición (% USDT)', new.notional_usdt, lim.max_position_usdt;
    end if;
    perform public.validate_buy_levels(new.entry_low, new.entry_high, new.invalidation, new.targets);
  end if;
  if new.expires_at <= now() then
    raise exception 'La propuesta ya está expirada (%)', new.expires_at;
  end if;
  return new;
end $$;

create function public.check_review() returns trigger
language plpgsql set search_path = '' as $$
declare
  proposer text;
begin
  select agent_id into proposer from public.trade_proposals where proposal_id = new.proposal_id;
  if proposer = new.reviewer_agent_id then
    raise exception 'Un agente no puede revisar su propia propuesta (%)', new.proposal_id;
  end if;
  return new;
end $$;

-- Una propuesta es ejecutable si no expiró, el último veredicto de otro agente es APPROVE,
-- el usuario la autorizó después de ese veredicto y aún no se ejecutó.
create view public.v_executable_proposals with (security_invoker = true) as
select p.*
from public.trade_proposals p
cross join lateral (
  select r.verdict, r.created_at
  from public.risk_reviews r
  where r.proposal_id = p.proposal_id and r.reviewer_agent_id <> p.agent_id
  order by r.id desc
  limit 1
) last_review
where p.expires_at > now()
  and last_review.verdict = 'APPROVE'
  and exists (
    select 1 from public.execution_authorizations a
    where a.proposal_id = p.proposal_id and a.created_at >= last_review.created_at
  )
  and not exists (select 1 from public.trades t where t.proposal_id = p.proposal_id);

create view public.v_open_positions with (security_invoker = true) as
select t.*
from public.trades t
where not exists (select 1 from public.trade_closures c where c.trade_ref = t.trade_ref);

create function public.gate_trade() returns trigger
language plpgsql set search_path = '' as $$
declare
  lim public.risk_limits;
  problems text[] := '{}';
  open_count integer;
begin
  select * into lim from public.risk_limits order by id desc limit 1;
  if lim.executor_agent_id is distinct from new.executor_agent_id then
    problems := problems || format('ejecutor %s no es el designado (%s)', new.executor_agent_id, lim.executor_agent_id);
  end if;
  if not exists (select 1 from public.v_executable_proposals v where v.proposal_id = new.proposal_id) then
    problems := problems || format('la propuesta %s no tenía APPROVE de otro agente + autorización del usuario vigentes', new.proposal_id);
  end if;
  select count(*) into open_count from public.v_open_positions;
  if open_count >= lim.max_open_positions then
    problems := problems || format('ya había %s posición(es) abierta(s); máximo %s', open_count, lim.max_open_positions);
  end if;
  if new.notional_usdt > lim.max_position_usdt then
    problems := problems || format('notional %s supera el máximo %s', new.notional_usdt, lim.max_position_usdt);
  end if;
  if not (new.symbol = any (lim.universe)) then
    problems := problems || format('%s fuera del universo', new.symbol);
  end if;

  new.gate_passed := cardinality(problems) = 0;
  new.gate_detail := case when new.gate_passed then 'ok' else array_to_string(problems, '; ') end;

  if not new.gate_passed then
    insert into public.events (agent_id, kind, severity, message, related_ref)
    values (new.executor_agent_id, 'protocol_violation', 'critical',
            'Trade registrado fuera de protocolo: ' || new.gate_detail, new.trade_ref);
  end if;
  return new;
end $$;

-- ---------------------------------------------------------------------------
-- Triggers
-- ---------------------------------------------------------------------------

do $$
declare
  t text;
begin
  foreach t in array array[
    'agents', 'risk_limits', 'analyses', 'trade_proposals', 'risk_reviews',
    'execution_authorizations', 'trades', 'trade_closures', 'portfolio_snapshots',
    'events', 'decision_scores'
  ] loop
    execute format('create trigger a_stamp_created_at before insert on public.%I for each row execute function public.stamp_created_at()', t);
    execute format('create trigger append_only before update or delete on public.%I for each row execute function public.forbid_mutation()', t);
    execute format('create trigger append_only_truncate before truncate on public.%I for each statement execute function public.forbid_mutation()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;

create trigger b_check_analysis before insert on public.analyses
  for each row execute function public.check_analysis();
create trigger b_check_proposal before insert on public.trade_proposals
  for each row execute function public.check_proposal();
create trigger b_check_review before insert on public.risk_reviews
  for each row execute function public.check_review();
create trigger b_gate_trade before insert on public.trades
  for each row execute function public.gate_trade();

-- ---------------------------------------------------------------------------
-- Vistas de lectura
-- ---------------------------------------------------------------------------

create view public.v_current_risk_limits with (security_invoker = true) as
select * from public.risk_limits order by id desc limit 1;

create view public.v_open_events with (security_invoker = true) as
select e.*
from public.events e
where e.resolves_event_id is null
  and not exists (select 1 from public.events r where r.resolves_event_id = e.id);

create view public.v_latest_portfolio with (security_invoker = true) as
select * from public.portfolio_snapshots order by id desc limit 1;

create view public.v_performance with (security_invoker = true) as
with closed as (
  select t.symbol, t.market_regime, c.pnl_usdt, c.pnl_pct, t.fee_usdt + c.fee_usdt as fees_usdt
  from public.trades t
  join public.trade_closures c on c.trade_ref = t.trade_ref
)
select
  count(*) as closed_trades,
  count(*) filter (where pnl_usdt > 0) as wins,
  round(avg((pnl_usdt > 0)::int)::numeric, 4) as win_rate,
  round(avg(pnl_usdt) filter (where pnl_usdt > 0), 4) as avg_win_usdt,
  round(avg(pnl_usdt) filter (where pnl_usdt <= 0), 4) as avg_loss_usdt,
  round(sum(pnl_usdt), 4) as realized_pnl_usdt,
  round(avg(pnl_usdt), 4) as expectancy_usdt,
  round(sum(pnl_usdt) filter (where pnl_usdt > 0)
        / nullif(-sum(pnl_usdt) filter (where pnl_usdt < 0), 0), 4) as profit_factor,
  round(sum(fees_usdt), 4) as total_fees_usdt
from closed;

-- Resultado de la competición a ciegas: última puntuación por decisión, agregada por agente.
create view public.v_agent_scoreboard with (security_invoker = true) as
with latest as (
  select distinct on (s.analysis_id, s.horizon_hours) s.*
  from public.decision_scores s
  order by s.analysis_id, s.horizon_hours, s.id desc
)
select
  a.agent_id,
  l.horizon_hours,
  count(*) as decisions_scored,
  count(*) filter (where l.outcome = 'NO_TRADE') as no_trade,
  count(*) filter (where l.outcome = 'NOT_FILLED') as not_filled,
  count(*) filter (where l.outcome = 'TARGET_HIT') as target_hit,
  count(*) filter (where l.outcome = 'STOP_HIT') as stop_hit,
  round(avg(l.r_multiple_after_fees), 3) as avg_r_after_fees,
  round(sum(l.r_multiple_after_fees), 3) as total_r_after_fees
from latest l
join public.analyses a on a.analysis_id = l.analysis_id
group by a.agent_id, l.horizon_hours;

do $$
declare
  v text;
begin
  foreach v in array array[
    'v_executable_proposals', 'v_open_positions', 'v_current_risk_limits', 'v_open_events',
    'v_latest_portfolio', 'v_performance', 'v_agent_scoreboard'
  ] loop
    execute format('revoke all on public.%I from anon, authenticated', v);
  end loop;
end $$;
