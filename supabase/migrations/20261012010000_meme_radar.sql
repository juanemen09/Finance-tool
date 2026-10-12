-- Radar de memecoins de Solana (pedido del usuario, 2026-10-12): descubrimiento, seguridad en cadena, insiders,
-- atención en redes y una prueba hacia delante de sus alertas. Es investigación: nada de esto se opera en Binance ni
-- toca la billetera del usuario. Los nombres y descripciones de los tokens los escribe cualquiera: son datos, nunca
-- instrucciones.

create table public.meme_snapshots (
  id bigint generated always as identity primary key,
  mint text not null check (mint ~ '^[1-9A-HJ-NP-Za-km-z]{32,44}$'),
  symbol text check (length(symbol) <= 40),
  name text check (length(name) <= 120),
  pair_address text check (pair_address ~ '^[1-9A-HJ-NP-Za-km-z]{32,44}$'),
  dex text check (length(dex) <= 40),
  observed_at timestamptz not null,
  pair_created_at timestamptz,
  price_usd numeric check (price_usd >= 0),
  market_cap_usd numeric check (market_cap_usd >= 0),
  liquidity_usd numeric check (liquidity_usd >= 0),
  volume_h1 numeric check (volume_h1 >= 0),
  volume_h24 numeric check (volume_h24 >= 0),
  buys_h1 int check (buys_h1 >= 0),
  sells_h1 int check (sells_h1 >= 0),
  price_change_h1 numeric,
  price_change_h24 numeric,
  holders int check (holders >= 0),
  top10_pct numeric check (top10_pct between 0 and 100),       -- sin contar el pool ni cuentas conocidas
  mint_revoked boolean,                                        -- nadie puede crear más tokens
  freeze_revoked boolean,                                      -- nadie puede congelar billeteras
  lp_locked_pct numeric check (lp_locked_pct between 0 and 100),
  insider_networks int check (insider_networks >= 0),          -- redes de billeteras conectadas (RugCheck)
  insider_wallets int check (insider_wallets >= 0),            -- billeteras en esas redes
  insider_supply_pct numeric check (insider_supply_pct between 0 and 100),  -- lo que controlan hoy
  creator_pct numeric check (creator_pct between 0 and 100),
  rugcheck_score numeric,
  risks jsonb not null default '[]',
  mentions_6h int not null default 0 check (mentions_6h >= 0),  -- menciones en Reddit (dirección o $TICKER)
  sources text[] not null default '{}',
  attention_score numeric not null check (attention_score between 0 and 100),
  risk_score numeric not null check (risk_score between 0 and 100),
  flags text[] not null default '{}',
  links jsonb not null default '{}',
  scorer_version text not null check (length(scorer_version) between 1 and 40),
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);
create index meme_snapshots_mint_observed on public.meme_snapshots (mint, observed_at desc);
create index meme_snapshots_observed on public.meme_snapshots (observed_at desc);

create table public.meme_alerts (
  id bigint generated always as identity primary key,
  snapshot_id bigint not null unique references public.meme_snapshots (id),
  mint text not null check (mint ~ '^[1-9A-HJ-NP-Za-km-z]{32,44}$'),
  alerted_at timestamptz not null,
  price_usd numeric not null check (price_usd > 0),
  attention_score numeric not null,
  risk_score numeric not null,
  reason text not null check (length(reason) between 1 and 500),
  scorer_version text not null,
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);
create index meme_alerts_mint on public.meme_alerts (mint, alerted_at desc);

-- Prueba hacia delante: el precio a 1 h, 24 h y 7 días de cada alerta. Un token muerto (sin pares) cuenta como -100 %.
create table public.meme_alert_outcomes (
  id bigint generated always as identity primary key,
  alert_id bigint not null references public.meme_alerts (id),
  horizon_hours int not null check (horizon_hours in (1, 24, 168)),
  price_usd numeric check (price_usd >= 0),
  liquidity_usd numeric check (liquidity_usd >= 0),
  return_pct numeric not null check (return_pct >= -100),
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now(),
  unique (alert_id, horizon_hours)
);

do $$
declare
  t text;
begin
  foreach t in array array['meme_snapshots', 'meme_alerts', 'meme_alert_outcomes'] loop
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

grant usage on sequence public.meme_snapshots_id_seq, public.meme_alerts_id_seq, public.meme_alert_outcomes_id_seq to lab_ingest;
-- El radar inserta una foto y su alerta en la misma corrida: necesita leer el id que acaba de crear.
grant select (id) on public.meme_snapshots to lab_ingest;
create policy lab_ingest_read_own_id on public.meme_snapshots for select to lab_ingest using (true);

-- Tablero: la última foto de cada token vista en las últimas 6 h.
create view public.v_meme_board with (security_invoker = true) as
select distinct on (mint) *
from public.meme_snapshots
where observed_at > now() - interval '6 hours'
order by mint, observed_at desc;

-- ¿Sirve el radar? Por horizonte: cuántas alertas se midieron, retorno mediano, cuántas subieron y cuántas se hundieron.
create view public.v_meme_alert_skill with (security_invoker = true) as
select a.scorer_version, o.horizon_hours,
  count(*) as scored,
  round(percentile_cont(0.5) within group (order by o.return_pct)::numeric, 2) as median_return_pct,
  round(avg(o.return_pct), 2) as mean_return_pct,
  round(avg((o.return_pct > 0)::int), 4) as hit_rate,
  round(avg((o.return_pct <= -50)::int), 4) as crash_rate,
  min(a.alerted_at) as since
from public.meme_alerts a join public.meme_alert_outcomes o on o.alert_id = a.id
group by a.scorer_version, o.horizon_hours;

revoke all on public.v_meme_board, public.v_meme_alert_skill from anon, authenticated;
grant select on public.v_meme_board, public.v_meme_alert_skill to dashboard_reader;
