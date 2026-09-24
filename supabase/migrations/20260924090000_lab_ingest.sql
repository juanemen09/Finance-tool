-- Rol de ingesta para el recolector de sentimiento (tools/ingest_sentiment.py --insert). Existe para ahorrar uso:
-- antes el agente copiaba decenas de titulares en SQL dentro de su respuesta cada hora. Este rol solo puede AÑADIR
-- filas de Claude en las dos tablas de sentimiento: no lee, no modifica y no toca propuestas, trades ni vetos.
-- Nace sin login: el usuario le pone la contraseña en el editor SQL y la conexión vive solo en su .env.

create role lab_ingest nologin;
alter role lab_ingest set statement_timeout = '30s';
grant usage on schema public to lab_ingest;
grant insert on public.news_items, public.sentiment_observations to lab_ingest;
grant usage on sequence public.news_items_id_seq, public.sentiment_observations_id_seq to lab_ingest;

create policy lab_ingest_insert on public.news_items for insert to lab_ingest
  with check (recorded_by_agent_id = 'claude');
create policy lab_ingest_insert on public.sentiment_observations for insert to lab_ingest
  with check (recorded_by_agent_id = 'claude');
