-- Pruebas de las tablas de sentimiento. Transacción revertida: no deja rastro.
begin;

create function pg_temp.expect_error(stmt text, fragment text) returns void language plpgsql as $$
begin
  execute stmt;
  raise exception 'Se esperaba un error con "%" y no hubo ninguno: %', fragment, stmt;
exception when others then
  if sqlerrm like 'Se esperaba un error%' then raise; end if;
  if position(fragment in sqlerrm) = 0 then
    raise exception 'Error distinto al esperado. Esperado "%", recibido "%"', fragment, sqlerrm;
  end if;
end $$;

insert into agents (id, display_name, role) select 'claude', 'Claude', 'risk'
where not exists (select 1 from agents where id = 'claude');

-- El mismo formato que genera ai_trading_lab.sentiment.to_sql, incluido el array de símbolos desde JSON.
insert into public.news_items (item_key, source, author, title, url, published_at, symbols, sentiment, sentiment_model, recorded_by_agent_id)
select item_key, source, author, title, url, published_at, symbols, sentiment, sentiment_model, 'claude'
from jsonb_to_recordset($j1$[
  {"item_key": "coindesk:test1", "source": "coindesk", "author": null, "title": "Bitcoin plunges", "url": "https://x/1",
   "published_at": "2099-01-01T00:00:00+00:00", "symbols": ["BTCUSDT", "ETHUSDT"], "sentiment": -0.6, "sentiment_model": "m"},
  {"item_key": "decrypt:test2", "source": "decrypt", "author": null, "title": "Markets calm", "url": "https://x/2",
   "published_at": "2099-01-01T00:00:00+00:00", "symbols": [], "sentiment": 0.5, "sentiment_model": "m"}
]$j1$::jsonb) as x(item_key text, source text, author text, title text, url text, published_at timestamptz,
                   symbols text[], sentiment numeric, sentiment_model text)
on conflict do nothing;

do $$ begin
  assert (select symbols from news_items where item_key = 'coindesk:test1') = array['BTCUSDT', 'ETHUSDT'],
    'el array JSON debe llegar como text[]';
  assert (select created_at from news_items where item_key = 'coindesk:test1') = now(), 'created_at lo pone la base';
end $$;

-- Repetir la ingesta no duplica nada.
insert into public.news_items (item_key, source, title, url, published_at, sentiment, sentiment_model, recorded_by_agent_id)
values ('coindesk:test1', 'coindesk', 'otro título', 'https://x/1', now(), 0, 'm', 'claude')
on conflict do nothing;
do $$ begin
  assert (select count(*) from news_items where item_key like '%:test%') = 2, 'el duplicado no debe entrar';
  assert (select title from news_items where item_key = 'coindesk:test1') = 'Bitcoin plunges', 'el original no cambia';
end $$;

-- Restricciones.
select pg_temp.expect_error($$insert into news_items (item_key, source, title, url, published_at, sentiment, sentiment_model, recorded_by_agent_id)
  values ('x:1', 'twitter', 't', 'https://x', now(), 0, 'm', 'claude')$$, 'news_items_source_check');
select pg_temp.expect_error($$insert into news_items (item_key, source, title, url, published_at, sentiment, sentiment_model, recorded_by_agent_id)
  values ('x:2', 'coindesk', 't', 'https://x', now(), 1.5, 'm', 'claude')$$, 'news_items_sentiment_check');
select pg_temp.expect_error($$insert into news_items (item_key, source, title, url, published_at, sentiment, sentiment_model, recorded_by_agent_id)
  values ('x:3', 'coindesk', 't', 'javascript:alert(1)', now(), 0, 'm', 'claude')$$, 'news_items_url_check');

-- Append-only.
select pg_temp.expect_error($$update news_items set title = 'x' where item_key = 'coindesk:test1'$$, 'append-only');
select pg_temp.expect_error($$delete from news_items where item_key = 'coindesk:test1'$$, 'append-only');

-- Observaciones: el Fear & Greed (sin símbolo) tampoco se duplica, gracias a nulls not distinct.
insert into sentiment_observations (source, metric, symbol, value, label, observed_at, recorded_by_agent_id) values
  ('alternative_me', 'fear_greed', null, 71, 'Greed', '2099-01-01T00:00:00Z', 'claude'),
  ('binance_futures', 'funding_rate', 'BTCUSDT', 0.00000132, null, '2099-01-01T00:00:00Z', 'claude'),
  ('binance_futures', 'funding_rate', 'BTCUSDT', 0.0001, null, '2099-01-01T08:00:00Z', 'claude');
insert into sentiment_observations (source, metric, symbol, value, label, observed_at, recorded_by_agent_id)
values ('alternative_me', 'fear_greed', null, 20, 'Fear', '2099-01-01T00:00:00Z', 'claude')
on conflict do nothing;
select pg_temp.expect_error($$update sentiment_observations set value = 1 where metric = 'fear_greed'$$, 'append-only');

do $$ begin
  assert (select count(*) from sentiment_observations where metric = 'fear_greed' and observed_at = '2099-01-01T00:00:00Z') = 1,
    'el duplicado del F&G (symbol null) no debe entrar';
  assert (select value from v_sentiment_latest where metric = 'fear_greed') = 71, 'el valor original se mantiene';
  assert (select value from v_sentiment_latest where metric = 'funding_rate' and symbol = 'BTCUSDT') = 0.0001,
    'v_sentiment_latest debe dar el valor más reciente';
end $$;

-- Tono agregado: un titular con dos activos cuenta en ambos; sin activo va a MERCADO.
insert into news_items (item_key, source, title, url, published_at, symbols, sentiment, sentiment_model, recorded_by_agent_id)
values ('coindesk:test3', 'coindesk', 'ETH and BTC slump', 'https://x/3', now() - interval '1 hour', '{BTCUSDT,ETHUSDT}', -0.4, 'm', 'claude'),
       ('decrypt:test4', 'decrypt', 'Calm', 'https://x/4', now() - interval '2 hours', '{}', 0.5, 'm', 'claude'),
       ('decrypt:test5', 'decrypt', 'Very old', 'https://x/5', now() - interval '3 days', '{BTCUSDT}', 0.9, 'm', 'claude');
do $$
declare
  btc record;
begin
  select * into btc from v_news_sentiment_24h where symbol = 'BTCUSDT';
  -- Base vacía (Docker): en BTC solo cuenta test3; test5 (hace 3 días) y test1 (fecha futura) quedan fuera.
  assert btc.items = 1 and btc.avg_sentiment = -0.4 and btc.negative_items = 1,
    format('BTC debe contar solo el titular reciente, no el viejo ni el futuro: %s', btc);
  assert exists (select 1 from v_news_sentiment_24h where symbol = 'MERCADO'), 'los titulares sin activo van a MERCADO';
end $$;

-- Sin acceso público.
do $$ begin
  assert not has_table_privilege('anon', 'public.news_items', 'select'), 'anon no debe leer news_items';
  assert not has_table_privilege('authenticated', 'public.sentiment_observations', 'insert'), 'authenticated no debe escribir';
  assert not has_table_privilege('anon', 'public.v_news_sentiment_24h', 'select'), 'anon no debe leer la vista';
end $$;

select 'sentiment_test OK' as resultado;
rollback;
