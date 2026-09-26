-- El usuario pidió el 2026-09-26 que su ausencia de 1 minuto cuente como conformidad ("mejor que sea 1 minuto de
-- ausencia mía, menos créditos empleados"). El mínimo de 5 lo había puesto la migración de la autorización
-- permanente; baja a 1. Los demás topes (pérdida por operación, R:R, límite semanal) no cambian.
alter table public.standing_authorizations drop constraint standing_authorizations_veto_minutes_check;
alter table public.standing_authorizations add constraint standing_authorizations_veto_minutes_check
  check (veto_minutes between 1 and 240);
