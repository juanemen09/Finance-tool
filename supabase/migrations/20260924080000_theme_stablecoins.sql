-- Las stablecoins son el dólar tokenizado: sus titulares también son del tema tokenización.
create or replace view public.v_theme_news with (security_invoker = true) as
select n.id, n.source, n.author, n.title, n.url, n.published_at, n.symbols, n.sentiment, t.themes
from public.news_items n
cross join lateral (
  select array_remove(array[
    case when n.title ~* '(tokeni[sz]|real[- ]world asset|\mrwas?\M|buidl|securitize|larry fink|dtcc|onchain (treasur|fund|stock|equit)|stablecoins?)'
         then 'tokenizacion' end,
    case when n.title ~* '(\moil\M|crude|brent|\mwti\M|opec|petr[oó]leo|natural gas|\mlng\M|\mgold\M|silver|copper|lithium|nickel|uranium|rare earth|critical mineral|\mminerals?\M|commodit|iron ore)'
         then 'materias_primas' end
  ], null) as themes
) t
where cardinality(t.themes) > 0;
