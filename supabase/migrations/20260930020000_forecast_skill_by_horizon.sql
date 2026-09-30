-- El criterio pre-registrado de TimesFM mide el horizonte de 7 días sumando los 5 activos, y el rollup anterior
-- no daba esa combinación (solo activo+horizonte, activo y total). Mismas columnas.
create or replace view public.v_forecast_skill with (security_invoker = true) as
select f.model, f.symbol, f.horizon_days,
  count(*) as scored,
  round(avg(o.direction_hit::int) filter (where o.direction_hit is not null), 4) as direction_hit_rate,
  count(*) filter (where o.direction_hit is not null) as direction_n,
  round(avg(o.inside_p10_p90::int), 4) as coverage_p10_p90,
  round(1 - avg(o.pinball_model) / nullif(avg(o.pinball_benchmark), 0), 4) as skill_vs_random_walk,
  min(f.origin_close_time) as since
from public.forecasts f join public.forecast_outcomes o on o.forecast_id = f.id
group by grouping sets ((f.model, f.symbol, f.horizon_days), (f.model, f.horizon_days), (f.model));
