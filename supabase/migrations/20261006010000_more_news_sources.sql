-- Cobertura de noticias ampliada (pedido del usuario el 2026-10-06: «que no se escape ni una noticia»).
-- Medios cripto, la Fed y la SEC por RSS, y los anuncios oficiales de Binance (nuevos listados y retiros).
alter table public.news_items drop constraint news_items_source_check;
alter table public.news_items add constraint news_items_source_check
  check (source in ('coindesk', 'cointelegraph', 'decrypt', 'reddit_cryptocurrency', 'bluesky',
                    'oilprice', 'cnbc_energy', 'investing_commodities',
                    'theblock', 'blockworks', 'bitcoinmagazine', 'cryptoslate', 'thedefiant', 'cryptobriefing',
                    'fed_press', 'sec_press', 'binance_listings', 'binance_delisting'));
