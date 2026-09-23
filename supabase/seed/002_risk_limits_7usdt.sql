-- Decisión del usuario del 2026-09-23: tope 7 USDT y Codex (chatgpt) confirmado como ejecutor.
-- Ya aplicado en Finance-tool (arxdfgphjybdxgdpqmkh); se guarda para poder reconstruir el diario.
begin;

insert into public.risk_limits (max_position_usdt, max_open_positions, universe, executor_agent_id, set_by, note)
values (
  7.00, 1, array['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'ONDOUSDT'], 'chatgpt', 'user',
  'Instrucción del usuario en chat con Claude (2026-09-23): "sube el tope a 7 USDT y confirma Codex como ejecutor". '
  || 'Tope 7 USDT deja ~40 % de margen sobre el minNotional de 5 USDT; ejecutor chatgpt confirmado explícitamente.'
);

insert into public.events (agent_id, kind, severity, message, related_ref, resolves_event_id)
select 'claude', 'resolution', 'info',
  'Resuelto por decisión del usuario: tope por posición subido a 7 USDT (risk_limits vigente). Una posición de 7 USDT '
  || 'sigue por encima del minNotional de 5 USDT salvo caída > 28 %, así que el stop es ejecutable.',
  'risk_limits', id
from public.events where kind = 'structural_risk' and related_ref = 'risk_limits';

commit;
