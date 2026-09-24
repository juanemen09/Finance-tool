-- Temas de tokenización y materias primas, y las fuentes nuevas. Transacción revertida: no deja rastro.
begin;

insert into agents (id, display_name, role) select 'claude', 'Claude', 'risk'
where not exists (select 1 from agents where id = 'claude');

insert into news_items (item_key, source, title, url, published_at, sentiment, sentiment_model, recorded_by_agent_id) values
  ('t:1', 'coindesk', 'BlackRock expands BUIDL tokenized treasury fund', 'https://x/1', now(), 0, 'm', 'claude'),
  ('t:2', 'oilprice', 'Crude oil rises as OPEC extends cuts', 'https://x/2', now(), 0, 'm', 'claude'),
  ('t:3', 'cnbc_energy', 'Gold and copper rally on critical minerals deal', 'https://x/3', now(), 0, 'm', 'claude'),
  ('t:4', 'decrypt', 'Tokenized gold demand surges', 'https://x/4', now(), 0, 'm', 'claude'),
  ('t:5', 'investing_commodities', 'Bitcoin miners boil over; toilets and golden retrievers', 'https://x/5', now(), 0, 'm', 'claude'),
  ('t:6', 'cointelegraph', 'Real-world assets onchain hit record', 'https://x/6', now(), 0, 'm', 'claude');

insert into sentiment_observations (source, metric, symbol, value, observed_at, recorded_by_agent_id) values
  ('defillama', 'stablecoin_supply_usd', null, 311e9, '2099-01-01', 'claude'),
  ('defillama', 'rwa_tvl_usd', null, 4.7e9, '2099-01-01', 'claude');

do $$
declare
  th text[];
begin
  select themes into th from v_theme_news where title like 'BlackRock%';
  assert th = array['tokenizacion'], format('BUIDL es tokenización: %s', th);
  select themes into th from v_theme_news where title like 'Crude%';
  assert th = array['materias_primas'], format('petróleo es materia prima: %s', th);
  select themes into th from v_theme_news where title like 'Tokenized gold%';
  assert th = array['tokenizacion', 'materias_primas'], format('oro tokenizado tiene los dos temas: %s', th);
  assert exists (select 1 from v_theme_news where title like 'Real-world%'), 'activos del mundo real es tokenización';
  -- "boil", "toilets" y "golden" no son petróleo ni oro: los límites de palabra evitan falsos positivos.
  assert not exists (select 1 from v_theme_news where title like 'Bitcoin miners%'), 'falso positivo por subcadena';
  assert not has_table_privilege('anon', 'public.v_theme_news', 'select'), 'anon no debe leer la vista';
  assert has_table_privilege('dashboard_reader', 'public.v_theme_news', 'select'), 'el panel debe poder leerla';
end $$;

select 'tokenization_test OK' as resultado;
rollback;
