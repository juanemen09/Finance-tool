-- Buzón entre agentes. Supabase no puede despertar a un agente: cada uno revisa su buzón
-- (v_pending_messages) al inicio de cada ejecución programada. Un mensaje se da por atendido
-- insertando un acuse en message_acks; el mensaje original nunca se modifica.

create table public.agent_messages (
  id bigint generated always as identity primary key,
  from_agent_id text not null references public.agents (id),
  to_agent_id text not null references public.agents (id),
  kind text not null check (kind in ('REVIEW_REQUEST', 'REVIEW_DONE', 'EXECUTION_DONE', 'ALERT', 'INFO')),
  related_ref text,
  body text not null,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  check (from_agent_id <> to_agent_id)
);

create table public.message_acks (
  id bigint generated always as identity primary key,
  message_id bigint not null unique references public.agent_messages (id),
  acked_by_agent_id text not null references public.agents (id),
  outcome text not null,
  created_at timestamptz not null default now()
);

create function public.check_message_ack() returns trigger
language plpgsql set search_path = '' as $$
declare
  recipient text;
begin
  select to_agent_id into recipient from public.agent_messages where id = new.message_id;
  if recipient is distinct from new.acked_by_agent_id then
    raise exception 'Solo el destinatario (%) puede dar por atendido el mensaje %', recipient, new.message_id;
  end if;
  return new;
end $$;

do $$
declare
  t text;
begin
  foreach t in array array['agent_messages', 'message_acks'] loop
    execute format('create trigger a_stamp_created_at before insert on public.%I for each row execute function public.stamp_created_at()', t);
    execute format('create trigger append_only before update or delete on public.%I for each row execute function public.forbid_mutation()', t);
    execute format('create trigger append_only_truncate before truncate on public.%I for each statement execute function public.forbid_mutation()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;

create trigger b_check_message_ack before insert on public.message_acks
  for each row execute function public.check_message_ack();

create index agent_messages_to_agent_idx on public.agent_messages (to_agent_id);

-- Mensajes sin atender y no caducados, por destinatario.
create view public.v_pending_messages with (security_invoker = true) as
select m.*
from public.agent_messages m
where not exists (select 1 from public.message_acks a where a.message_id = m.id)
  and (m.expires_at is null or m.expires_at > now());

-- Una fila por propuesta con su situación actual: lo primero que mira cualquier agente o el usuario.
create view public.v_proposal_status with (security_invoker = true) as
select
  p.proposal_id,
  p.agent_id as proposer,
  p.symbol,
  p.side,
  p.entry_low,
  p.entry_high,
  p.invalidation,
  p.targets,
  p.notional_usdt,
  p.expires_at,
  r.reviewer_agent_id as last_reviewer,
  r.verdict as last_verdict,
  r.review_id as last_review_id,
  exists (select 1 from public.execution_authorizations a
          where a.proposal_id = p.proposal_id and a.created_at >= r.created_at) as authorized_after_review,
  exists (select 1 from public.v_executable_proposals e where e.proposal_id = p.proposal_id) as executable,
  (select t.trade_ref from public.trades t where t.proposal_id = p.proposal_id) as trade_ref,
  case
    when exists (select 1 from public.trades t where t.proposal_id = p.proposal_id) then 'EXECUTED'
    when p.expires_at <= now() then 'EXPIRED'
    when r.verdict is null then 'AWAITING_REVIEW'
    when r.verdict <> 'APPROVE' then 'NOT_APPROVED'
    when exists (select 1 from public.v_executable_proposals e where e.proposal_id = p.proposal_id) then 'READY_TO_EXECUTE'
    else 'AWAITING_USER_AUTHORIZATION'
  end as status,
  p.created_at
from public.trade_proposals p
left join lateral (
  select rr.reviewer_agent_id, rr.verdict, rr.review_id, rr.created_at
  from public.risk_reviews rr
  where rr.proposal_id = p.proposal_id and rr.reviewer_agent_id <> p.agent_id
  order by rr.id desc
  limit 1
) r on true;

revoke all on public.v_pending_messages from anon, authenticated;
revoke all on public.v_proposal_status from anon, authenticated;
