-- Tokenización y materias primas (pedido del usuario, 2026-09-24): nuevas fuentes y una vista temática.
-- Las métricas de tokenización (oferta de stablecoins, total invertido en activos del mundo real tokenizados)
-- vienen de DefiLlama; los titulares de materias primas, de tres RSS nuevos. Siguen siendo contexto: nada de
-- esto respalda operaciones hasta pasar el hard testing.

alter table public.sentiment_observations drop constraint sentiment_observations_source_check;
alter table public.sentiment_observations add constraint sentiment_observations_source_check
  check (source in ('alternative_me', 'binance_futures', 'defillama'));
alter table public.sentiment_observations drop constraint sentiment_observations_metric_check;
alter table public.sentiment_observations add constraint sentiment_observations_metric_check
  check (metric in ('fear_greed', 'funding_rate', 'long_short_account_ratio', 'stablecoin_supply_usd', 'rwa_tvl_usd'));

alter table public.news_items drop constraint news_items_source_check;
alter table public.news_items add constraint news_items_source_check
  check (source in ('coindesk', 'cointelegraph', 'decrypt', 'reddit_cryptocurrency', 'bluesky',
                    'oilprice', 'cnbc_energy', 'investing_commodities'));

-- Temas por palabras clave, calculados al leer: cubre también los titulares guardados antes de esta migración.
create view public.v_theme_news with (security_invoker = true) as
select n.id, n.source, n.author, n.title, n.url, n.published_at, n.symbols, n.sentiment, t.themes
from public.news_items n
cross join lateral (
  select array_remove(array[
    case when n.title ~* '(tokeni[sz]|real[- ]world asset|\mrwas?\M|buidl|securitize|larry fink|dtcc|onchain (treasur|fund|stock|equit))'
         then 'tokenizacion' end,
    case when n.title ~* '(\moil\M|crude|brent|\mwti\M|opec|petr[oó]leo|natural gas|\mlng\M|\mgold\M|silver|copper|lithium|nickel|uranium|rare earth|critical mineral|\mminerals?\M|commodit|iron ore)'
         then 'materias_primas' end
  ], null) as themes
) t
where cardinality(t.themes) > 0;

revoke all on public.v_theme_news from anon, authenticated;
grant select on public.v_theme_news to dashboard_reader;
