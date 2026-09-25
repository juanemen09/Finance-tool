-- El rol de ingesta solo añade filas de Claude en las tablas de sentimiento. Transacción revertida.
begin;

-- postgres administra los roles pero no puede asumirlos (PG16): se le da SET solo dentro de esta transacción.
grant lab_ingest, dashboard_reader to current_user with set true;

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
insert into agents (id, display_name, role) select 'chatgpt', 'ChatGPT', 'execution'
where not exists (select 1 from agents where id = 'chatgpt');

set local role lab_ingest;

-- Lo que hace el recolector: insertar ignorando duplicados, dos veces seguidas.
insert into news_items (item_key, source, title, url, published_at, sentiment, sentiment_model, recorded_by_agent_id)
values ('ingest:1', 'coindesk', 't', 'https://x/1', now(), 0, 'm', 'claude') on conflict do nothing;
insert into news_items (item_key, source, title, url, published_at, sentiment, sentiment_model, recorded_by_agent_id)
values ('ingest:1', 'coindesk', 't', 'https://x/1', now(), 0, 'm', 'claude') on conflict do nothing;
insert into sentiment_observations (source, metric, symbol, value, observed_at, recorded_by_agent_id)
values ('alternative_me', 'fear_greed', null, 50, '2099-01-01', 'claude') on conflict do nothing;

-- Nada más.
select pg_temp.expect_error($$select count(*) from news_items$$, 'permission denied');
select pg_temp.expect_error($$update news_items set title = 'x'$$, 'permission denied');
select pg_temp.expect_error($$delete from sentiment_observations$$, 'permission denied');
select pg_temp.expect_error($$insert into events (agent_id, kind, severity, message) values ('claude', 'x', 'info', 'x')$$, 'permission denied');
select pg_temp.expect_error($$insert into user_vetoes (proposal_id, user_message_quote, recorded_by_agent_id) values ('P', 'x', 'claude')$$, 'permission denied');
select pg_temp.expect_error($$insert into news_items (item_key, source, title, url, published_at, sentiment, sentiment_model, recorded_by_agent_id)
  values ('ingest:2', 'coindesk', 't', 'https://x/2', now(), 0, 'm', 'chatgpt')$$, 'row-level security');

reset role;

do $$ begin
  assert (select count(*) from news_items where item_key = 'ingest:1') = 1, 'el duplicado no debe entrar';
  assert not exists (select 1 from pg_roles where rolname = 'lab_ingest' and (rolsuper or rolbypassrls or rolcreaterole or rolcanlogin)),
    'sin privilegios especiales ni login hasta que el usuario le ponga contraseña';
end $$;

select 'lab_ingest_test OK' as resultado;
rollback;
