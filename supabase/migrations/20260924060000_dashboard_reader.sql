-- Rol de solo lectura para el centro de mando local (dashboard/). Nace sin login: el usuario le pone la
-- contraseña él mismo en el editor SQL (alter role dashboard_reader login password '...'), y la conexión
-- vive solo en su .env. Aunque el panel tuviera un error, este rol no puede escribir, aprobar ni vetar nada.
--
-- RLS está activado sin políticas en todas las tablas: sin una política de lectura para este rol no vería
-- ninguna fila. Las políticas son solo `for select` y solo `to dashboard_reader`.

create role dashboard_reader nologin;
alter role dashboard_reader set statement_timeout = '10s';
alter role dashboard_reader set default_transaction_read_only = on;
grant usage on schema public to dashboard_reader;

do $$
declare
  t text;
begin
  for t in select table_name from information_schema.tables
           where table_schema = 'public' and table_type = 'BASE TABLE' loop
    execute format('grant select on public.%I to dashboard_reader', t);
    execute format('create policy dashboard_read on public.%I for select to dashboard_reader using (true)', t);
  end loop;
  for t in select table_name from information_schema.views where table_schema = 'public' loop
    execute format('grant select on public.%I to dashboard_reader', t);
  end loop;
end $$;
