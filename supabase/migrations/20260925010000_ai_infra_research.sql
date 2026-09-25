-- Tesis de infraestructura de IA (pedido del usuario, 2026-09-24): el libro 13F de Situational Awareness LP, el capex
-- de los compradores de IA y la oferta física (memoria de Corea, pedidos de Taiwán, cartera de turbinas).
-- Es investigación que se informa al usuario: nada de esto respalda una operación ni se opera en este laboratorio.
-- Mismas reglas que el resto del diario: append-only, created_at lo pone la base, sin acceso público.

create table public.research_facts (
  id bigint generated always as identity primary key,
  fact_key text not null unique,               -- el mismo hecho (fuente + periodo + entidad) no entra dos veces
  topic text not null check (topic in ('13f', 'ai_demand', 'ai_supply')),
  metric text not null check (length(metric) between 1 and 80),
  entity text not null check (length(entity) between 1 and 80),
  period_end date not null,                    -- el periodo que mide la fuente, no el día de la descarga
  value numeric,                               -- null en las citas textuales
  unit text not null,
  detail jsonb not null default '{}',
  source_url text not null check (source_url like 'https://%'),
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

create table public.research_reports (
  id bigint generated always as identity primary key,
  report_key text not null unique,             -- tipo + hash de los datos: sin datos nuevos no hay informe nuevo
  kind text not null check (kind in ('13F_BOOK', 'AI_DEMAND', 'AI_SUPPLY', 'AI_BOTTLENECK')),
  as_of date not null,
  title text not null check (length(title) between 1 and 200),
  body text not null check (length(body) between 1 and 8000),
  data jsonb not null default '{}',
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

create index research_facts_lookup on public.research_facts (topic, metric, entity, period_end desc);
create index research_reports_kind on public.research_reports (kind, id desc);

do $$
declare
  t text;
begin
  foreach t in array array['research_facts', 'research_reports'] loop
    execute format('create trigger a_stamp_created_at before insert on public.%I for each row execute function public.stamp_created_at()', t);
    execute format('create trigger append_only before update or delete on public.%I for each row execute function public.forbid_mutation()', t);
    execute format('create trigger append_only_truncate before truncate on public.%I for each statement execute function public.forbid_mutation()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    -- El panel lee; el recolector solo añade filas de Claude.
    execute format('grant select on public.%I to dashboard_reader', t);
    execute format('create policy dashboard_read on public.%I for select to dashboard_reader using (true)', t);
    execute format('grant insert on public.%I to lab_ingest', t);
    execute format('create policy lab_ingest_insert on public.%I for insert to lab_ingest with check (recorded_by_agent_id = ''claude'')', t);
  end loop;
end $$;

grant usage on sequence public.research_facts_id_seq, public.research_reports_id_seq to lab_ingest;

-- Último informe de cada tipo, para el panel y para comparar con el mes anterior.
create view public.v_research_latest with (security_invoker = true) as
select distinct on (kind) kind, report_key, as_of, title, body, data, recorded_by_agent_id, created_at
from public.research_reports
order by kind, id desc;

revoke all on public.v_research_latest from anon, authenticated;
grant select on public.v_research_latest to dashboard_reader;
