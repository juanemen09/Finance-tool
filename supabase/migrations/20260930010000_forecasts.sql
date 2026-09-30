-- Pronósticos de TimesFM 3.0 en papel (pedido del usuario, 2026-09-30; investigación personal no comercial) y su
-- puntuación frente a un paseo aleatorio cuando llega el precio real. Contexto, no señal: nada de esto respalda
-- una operación hasta pasar el hard testing hacia delante (docs/plans/tsfm-forward-test.md).

create table public.forecasts (
  id bigint generated always as identity primary key,
  model text not null check (length(model) between 1 and 40),
  symbol text not null check (symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'ONDOUSDT')),
  horizon_days int not null check (horizon_days between 1 and 30),
  origin_close_time timestamptz not null,       -- cierre diario con el que se pronosticó
  target_close_time timestamptz not null,       -- cierre diario pronosticado
  last_close numeric not null check (last_close > 0),
  quantiles jsonb not null,                     -- p10..p90 del precio según el modelo
  benchmark jsonb not null,                     -- p10..p90 del paseo aleatorio (retornos empíricos del último año)
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now(),
  unique (model, symbol, horizon_days, origin_close_time),
  check (target_close_time > origin_close_time)
);

create table public.forecast_outcomes (
  id bigint generated always as identity primary key,
  forecast_id bigint not null unique references public.forecasts (id),
  realized_close numeric not null check (realized_close > 0),
  pinball_model numeric not null,               -- pérdida cuantil media relativa al último cierre (menor = mejor)
  pinball_benchmark numeric not null,
  direction_hit boolean,                        -- null si el modelo o el mercado no se movieron
  inside_p10_p90 boolean not null,
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

do $$
declare
  t text;
begin
  foreach t in array array['forecasts', 'forecast_outcomes'] loop
    execute format('create trigger a_stamp_created_at before insert on public.%I for each row execute function public.stamp_created_at()', t);
    execute format('create trigger append_only before update or delete on public.%I for each row execute function public.forbid_mutation()', t);
    execute format('create trigger append_only_truncate before truncate on public.%I for each statement execute function public.forbid_mutation()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to dashboard_reader', t);
    execute format('create policy dashboard_read on public.%I for select to dashboard_reader using (true)', t);
    execute format('grant insert on public.%I to lab_ingest', t);
    execute format('create policy lab_ingest_insert on public.%I for insert to lab_ingest with check (recorded_by_agent_id = ''claude'')', t);
  end loop;
end $$;

grant usage on sequence public.forecasts_id_seq, public.forecast_outcomes_id_seq to lab_ingest;

-- ¿Sirve? Por modelo, activo y horizonte: aciertos de dirección, cobertura de la banda y mejora frente al paseo
-- aleatorio (skill > 0 = el modelo se equivoca menos que la referencia).
create view public.v_forecast_skill with (security_invoker = true) as
select f.model, f.symbol, f.horizon_days,
  count(*) as scored,
  round(avg(o.direction_hit::int) filter (where o.direction_hit is not null), 4) as direction_hit_rate,
  count(*) filter (where o.direction_hit is not null) as direction_n,
  round(avg(o.inside_p10_p90::int), 4) as coverage_p10_p90,
  round(1 - avg(o.pinball_model) / nullif(avg(o.pinball_benchmark), 0), 4) as skill_vs_random_walk,
  min(f.origin_close_time) as since
from public.forecasts f join public.forecast_outcomes o on o.forecast_id = f.id
group by rollup (f.model, f.symbol, f.horizon_days);

-- Último pronóstico de cada activo y horizonte (contexto para los análisis y el panel).
create view public.v_forecast_latest with (security_invoker = true) as
select distinct on (model, symbol, horizon_days) model, symbol, horizon_days, origin_close_time, target_close_time,
  last_close, quantiles, round((quantiles ->> 'p50')::numeric / last_close - 1, 5) as median_return
from public.forecasts
order by model, symbol, horizon_days, origin_close_time desc;

revoke all on public.v_forecast_skill, public.v_forecast_latest from anon, authenticated;
grant select on public.v_forecast_skill, public.v_forecast_latest to dashboard_reader;
