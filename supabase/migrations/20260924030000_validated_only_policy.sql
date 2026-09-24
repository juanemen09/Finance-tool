-- Política del usuario (2026-09-24): en cuanto exista una estrategia LIVE_ELIGIBLE, solo se pueden proponer
-- compras respaldadas por una estrategia LIVE_ELIGIBLE. Las ideas discrecionales se registran en `analyses`
-- y se puntúan, pero no llegan a `trade_proposals`.

alter table public.trade_proposals add column strategy_id text references public.strategies (strategy_id);

create function public.check_validated_only() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.side = 'BUY' and exists (
    select 1 from public.strategies s where public.latest_strategy_status(s.strategy_id) = 'LIVE_ELIGIBLE'
  ) then
    if new.strategy_id is null then
      raise exception 'Hay estrategias validadas: una compra debe indicar strategy_id de una estrategia LIVE_ELIGIBLE';
    end if;
    if public.latest_strategy_status(new.strategy_id) is distinct from 'LIVE_ELIGIBLE' then
      raise exception 'La estrategia % no está LIVE_ELIGIBLE', new.strategy_id;
    end if;
  end if;
  return new;
end $$;

create trigger c_check_validated_only before insert on public.trade_proposals
  for each row execute function public.check_validated_only();
