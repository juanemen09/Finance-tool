-- Autorización permanente con ventana de veto (decisión del usuario, 2026-09-24).
-- Si el usuario no responde dentro de veto_minutes tras el APPROVE del agente revisor, la propuesta queda
-- autorizada, pero SOLO si cumple todas las condiciones medibles de abajo. Nada garantiza beneficio; lo que
-- se garantiza es la pérdida máxima por operación y por semana, y que la estrategia demostró edge en pruebas.

create table public.standing_authorizations (
  id bigint generated always as identity primary key,
  set_by text not null check (set_by = 'user'),
  active boolean not null,
  veto_minutes integer not null check (veto_minutes between 5 and 240),
  max_loss_usdt numeric(12, 4) not null check (max_loss_usdt > 0),
  min_reward_risk numeric(6, 2) not null check (min_reward_risk >= 1),
  weekly_loss_limit_usdt numeric(12, 4) not null check (weekly_loss_limit_usdt > 0),
  user_message_quote text not null,
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

-- El usuario bloquea una propuesta concreta diciéndolo en el chat a cualquier agente.
create table public.user_vetoes (
  id bigint generated always as identity primary key,
  proposal_id text not null references public.trade_proposals (proposal_id),
  user_message_quote text not null,
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

do $$
declare
  t text;
begin
  foreach t in array array['standing_authorizations', 'user_vetoes'] loop
    execute format('create trigger a_stamp_created_at before insert on public.%I for each row execute function public.stamp_created_at()', t);
    execute format('create trigger append_only before update or delete on public.%I for each row execute function public.forbid_mutation()', t);
    execute format('create trigger append_only_truncate before truncate on public.%I for each statement execute function public.forbid_mutation()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;

-- Cada condición por separado, para que cualquiera vea exactamente por qué una propuesta sí o no se autoriza.
-- p_at existe para poder probar la ventana de veto sin esperar en tiempo real.
create function public.auto_authorization_status(p_proposal_id text, p_at timestamptz) returns jsonb
language plpgsql stable set search_path = '' as $$
declare
  p public.trade_proposals;
  sa public.standing_authorizations;
  rv record;
  loss numeric;
  rr numeric;
  week_pnl numeric;
  checks jsonb;
begin
  select * into p from public.trade_proposals where proposal_id = p_proposal_id;
  select * into sa from public.standing_authorizations order by id desc limit 1;
  select r.verdict, r.created_at into rv from public.risk_reviews r
  where r.proposal_id = p_proposal_id and r.reviewer_agent_id <> p.agent_id
  order by r.id desc limit 1;
  if p.side = 'BUY' and p.entry_high > p.invalidation and p.targets is not null then
    -- Pérdida si salta el stop desde el peor precio de la zona, más comisión y deslizamiento de ida y vuelta.
    loss := p.notional_usdt * (p.entry_high - p.invalidation) / p.entry_high + p.notional_usdt * 2 * 0.0015;
    rr := (p.targets[1] - p.entry_high) / (p.entry_high - p.invalidation);
  end if;
  select coalesce(sum(c.pnl_usdt), 0) into week_pnl
  from public.trade_closures c where c.closed_at > p_at - interval '7 days';

  checks := jsonb_build_object(
    'standing_authorization_active', coalesce(sa.active, false),
    'strategy_live_eligible', coalesce(p.strategy_id is not null
                                       and public.latest_strategy_status(p.strategy_id) = 'LIVE_ELIGIBLE', false),
    'reviewed_approve', coalesce(rv.verdict = 'APPROVE', false),
    'veto_window_elapsed', coalesce(p_at >= rv.created_at + make_interval(mins => sa.veto_minutes), false),
    'not_vetoed', not exists (select 1 from public.user_vetoes v where v.proposal_id = p_proposal_id),
    'not_expired', coalesce(p.expires_at > p_at, false),
    'max_loss_ok', coalesce(loss <= sa.max_loss_usdt, false),
    'reward_risk_ok', coalesce(rr >= sa.min_reward_risk, false),
    'weekly_loss_ok', coalesce(week_pnl > -sa.weekly_loss_limit_usdt, false),
    'executor_permissions_ok', not exists (select 1 from public.v_open_events e where e.kind = 'permissions_review'),
    'no_open_position', not exists (select 1 from public.v_open_positions),
    'not_executed', not exists (select 1 from public.trades t where t.proposal_id = p_proposal_id)
  );
  return checks || jsonb_build_object(
    'estimated_max_loss_usdt', round(loss, 4),
    'reward_risk', round(rr, 2),
    'auto_ok', not exists (select 1 from jsonb_each(checks) c where c.value <> 'true'::jsonb)
  );
end $$;

-- Ejecutable = APPROVE de otro agente, sin veto, sin ejecutar, no expirada, y además autorizada por el usuario
-- (explícitamente, después del APPROVE) o por la autorización permanente.
create or replace view public.v_executable_proposals with (security_invoker = true) as
select p.*, case when ua.user_authorized then 'USER' else 'STANDING' end as authorization_mode
from public.trade_proposals p
cross join lateral (
  select r.verdict, r.created_at
  from public.risk_reviews r
  where r.proposal_id = p.proposal_id and r.reviewer_agent_id <> p.agent_id
  order by r.id desc
  limit 1
) last_review
cross join lateral (
  select exists (
    select 1 from public.execution_authorizations a
    where a.proposal_id = p.proposal_id and a.created_at >= last_review.created_at
  ) as user_authorized
) ua
where p.expires_at > now()
  and last_review.verdict = 'APPROVE'
  and not exists (select 1 from public.trades t where t.proposal_id = p.proposal_id)
  and not exists (select 1 from public.user_vetoes v where v.proposal_id = p.proposal_id)
  and (ua.user_authorized or (public.auto_authorization_status(p.proposal_id, now()) ->> 'auto_ok')::boolean);

revoke all on public.v_executable_proposals from anon, authenticated;
