-- El usuario decidió (2026-09-26) que su "autorizo" valga aunque lo dé antes de la revisión del otro agente.
-- Motivo: el 2026-09-26 autorizó LINK a las 07:18Z, Codex aprobó a las 08:17Z con el precio en zona, y la
-- propuesta venció sin comprarse porque solo contaban las autorizaciones posteriores a la última revisión.
-- Sigue haciendo falta que el ÚLTIMO veredicto del otro agente sea APPROVE (un WAIT o REJECT posterior la
-- bloquea), que no haya veto, que no haya vencido y que no se haya ejecutado.
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
    select 1 from public.execution_authorizations a where a.proposal_id = p.proposal_id
  ) as user_authorized
) ua
where p.expires_at > now()
  and last_review.verdict = 'APPROVE'
  and not exists (select 1 from public.trades t where t.proposal_id = p.proposal_id)
  and not exists (select 1 from public.user_vetoes v where v.proposal_id = p.proposal_id)
  and (ua.user_authorized or (public.auto_authorization_status(p.proposal_id, now()) ->> 'auto_ok')::boolean);

revoke all on public.v_executable_proposals from anon, authenticated;
