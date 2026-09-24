-- Sentimiento del mercado: indicadores (Fear & Greed, funding, largo/corto) y titulares con su puntuación.
-- Es contexto, no una señal validada: nada aquí respalda una operación hasta pasar el hard testing.
-- Mismas reglas que el resto del diario: append-only, created_at lo pone la base, sin acceso público.
-- Las fuentes sin historial (titulares) solo se podrán probar con lo que se guarde desde ahora.

create table public.sentiment_observations (
  id bigint generated always as identity primary key,
  source text not null check (source in ('alternative_me', 'binance_futures')),
  metric text not null check (metric in ('fear_greed', 'funding_rate', 'long_short_account_ratio')),
  symbol text,                                 -- null = todo el mercado (Fear & Greed)
  value numeric not null,
  label text,
  observed_at timestamptz not null,            -- el momento que mide la fuente, no el de la descarga
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now(),
  unique nulls not distinct (source, metric, symbol, observed_at)
);

create table public.news_items (
  id bigint generated always as identity primary key,
  item_key text not null unique,               -- fuente + hash del guid: el mismo titular no entra dos veces
  source text not null check (source in ('coindesk', 'cointelegraph', 'decrypt', 'reddit_cryptocurrency', 'bluesky')),
  author text,
  title text not null check (length(title) between 1 and 500),
  url text not null check (url like 'https://%'),
  published_at timestamptz not null,
  symbols text[] not null default '{}',
  sentiment numeric not null check (sentiment between -1 and 1),
  sentiment_model text not null,
  recorded_by_agent_id text not null references public.agents (id),
  created_at timestamptz not null default now()
);

create index news_items_published_at on public.news_items (published_at desc);
create index sentiment_observations_lookup on public.sentiment_observations (metric, symbol, observed_at desc);

do $$
declare
  t text;
begin
  foreach t in array array['sentiment_observations', 'news_items'] loop
    execute format('create trigger a_stamp_created_at before insert on public.%I for each row execute function public.stamp_created_at()', t);
    execute format('create trigger append_only before update or delete on public.%I for each row execute function public.forbid_mutation()', t);
    execute format('create trigger append_only_truncate before truncate on public.%I for each statement execute function public.forbid_mutation()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;

-- Último valor de cada indicador.
create view public.v_sentiment_latest with (security_invoker = true) as
select distinct on (source, metric, symbol) source, metric, symbol, value, label, observed_at
from public.sentiment_observations
order by source, metric, symbol, observed_at desc;

-- Tono de los titulares de las últimas 24h por activo ('MERCADO' = sin activo concreto).
create view public.v_news_sentiment_24h with (security_invoker = true) as
select s.symbol,
  count(*) as items,
  round(avg(n.sentiment), 3) as avg_sentiment,
  count(*) filter (where n.sentiment <= -0.3) as negative_items,
  count(*) filter (where n.sentiment >= 0.3) as positive_items,
  max(n.published_at) as latest_at
from public.news_items n
cross join lateral unnest(case when cardinality(n.symbols) = 0 then array['MERCADO'] else n.symbols end) as s(symbol)
where n.published_at > now() - interval '24 hours'
  and n.published_at <= now() + interval '1 hour'   -- una fecha futura es un error de la fuente, no una noticia
group by s.symbol;

revoke all on public.v_sentiment_latest from anon, authenticated;
revoke all on public.v_news_sentiment_24h from anon, authenticated;
