# Sumar (y dar de baja) a una persona

Guía para el fundador. Vale igual para la primera persona que para la décima: el rol decide los accesos, y todo
queda registrado en el diario (`team_members`, `team_member_events`).

## Alta

1. **Elige handle y rol.** El handle es corto, en minúsculas y con `_` (por ejemplo `ana_m`); también nombra su rol
   de base (`team_ana_m`). Roles: `python -m team roles`. Ante la duda, empieza por `observer` o `analyst` y sube de
   rol cuando lo haya ganado.

2. **Regístralo en el diario.** Genera el SQL y ejecútalo en el SQL Editor de Supabase (o pídele a Claude que lo
   ejecute con el conector, citando tu mensaje):

   ```bash
   python -m team sql join --handle ana_m --name "Ana M." --role developer --github ana-m \
     --grant github:praxiguard:read --note "Fundador, 2026-09-27: 'sumen a Ana como developer con PraxiGuard'"
   ```

   El nombre solo viaja en ese SQL, nunca a un archivo del repositorio. `--grant` añade accesos opcionales del rol.
   La base rechaza cualquier acceso a Binance, escritura en el diario o permisos de decisión (`journal:*`).

3. **Rol de base personal** (analista y desarrollador). El mismo SQL trae el `create role team_<handle>`, que
   hereda `dashboard_reader`: lee el diario y no escribe nada. Ponle contraseña tú en el SQL Editor
   (`alter role team_ana_m with login password '...'`) y entrégala en persona o por un gestor de contraseñas. Su
   `.env` lleva `DASHBOARD_DATABASE_URL=postgresql://team_ana_m.<ref>:<contraseña>@<host del pooler>:5432/postgres`.
   Un rol por persona permite quitar el acceso a una sin tocar a las demás.

4. **GitHub.** En cada repo de sus accesos: Settings → Collaborators → Add people, con el permiso del recurso
   (`github:<repo>:read` = Read, `github:<repo>:write` = Write). Nunca Admin. Protege `main` una vez (Settings →
   Branches → Add rule): pull request obligatorio con revisión, y "Require review from Code Owners" para que
   `.github/CODEOWNERS` te exija a ti en cada cambio. Es lo que evita que un cambio en `AGENTS.md` llegue a los
   agentes sin tu revisión.

5. **Cuentas de IA.** Cada persona usa su propia cuenta de Claude y de ChatGPT. No compartas la tuya: tus agentes
   tienen conectores a Binance, Supabase y Gmail.

6. **Entrega el plan.**

   ```bash
   python -m team plan --handle ana_m --role developer --grant github:praxiguard:read --out team_local/ana_m.md
   ```

   `team_local/` está en `.gitignore`. El plan no lleva su nombre, solo el handle.

## Seguimiento

- Quién está y cuánto avanzó: `select * from v_team_roster;`
- Accesos vigentes: `select * from v_team_access order by member_id;`
- Paso terminado (lo avisa la persona): `python -m team sql step --handle ana_m --step entorno-local --note "..."`
- Cambio de rol o de acceso: `python -m team sql role ...` y `python -m team sql grant ... [--revoke]`

## Baja

```bash
python -m team sql leave --handle ana_m --note "Fundador, 2026-12-01: 'Ana deja el equipo'"
```

Registra la baja y desactiva su rol de base. Después quita sus accesos en GitHub y Vercel, y registra las
revocaciones con la última sentencia del mismo SQL. `v_team_offboarding_pending` debe quedar vacía. Si alguna clave
pudo pasar por sus manos, rótala.

## Cambiar las reglas

Los roles y los pasos del onboarding están en `config/team/roles.json`; el inventario, en `config/team/stack.json`
(y `docs/team/stack.md` se regenera con `python -m team stack --markdown > docs/team/stack.md`). Los detalles internos
de los repos privados van en `config/team/stack.private.json`, que git ignora. Dar a un miembro permisos hoy
prohibidos (Binance, escribir en el diario, autorizar o vetar) exige una migración nueva: es una decisión tuya y
deliberada, no un ajuste de configuración.
