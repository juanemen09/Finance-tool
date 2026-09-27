"""Lo que produce el módulo de equipo: el mapa del stack, el plan de onboarding de cada persona y el SQL de alta,
cambios y baja para el diario (tablas team_members y team_member_events).

El SQL se imprime para que lo ejecute el fundador (o su agente con el conector de Supabase); este módulo no se conecta
a ninguna base. Los nombres de las personas solo viajan en ese SQL, nunca en archivos del repositorio.
"""
from team.catalog import GITHUB_LOGIN, HANDLE, KINDS, RESOURCE, STEP_ID, WHEN, grant_satisfies, resource_forbidden

DECIDERS = ("user", "member", "claude", "chatgpt")
RULES_URL = "https://github.com/juanemen09/Finance-tool/blob/main/docs/team/README.md#reglas-de-oro"


def render_stack_markdown(catalog, role_id=None, include_private=False):
    """Sin stack.private.json salvo que se pida: docs/team/stack.md se publica en un repositorio público."""
    items = catalog.items_for(role_id, include_private)
    title = f"rol {catalog.role(role_id)['name']}" if role_id else "toda la startup"
    lines = [f"# Mapa de herramientas ({title})", "",
             "Generado con `python -m team stack --markdown` desde `config/team/stack.json`. No lo edites a mano.", ""]
    for kind, heading in KINDS.items():
        group = [i for i in items if i["kind"] == kind]
        if not group:
            continue
        lines += [f"## {heading}", ""]
        if kind == "repo":
            lines += ["| Repo | Visibilidad | Qué es | Stack | Por dónde empezar |", "|---|---|---|---|---|"]
            lines += [f"| [{i['name']}]({i['url']}) | {i['visibility']} | {i['what']} | {i['stack']} | {i['start']} |"
                      for i in group]
        elif kind == "app":
            lines += ["| Herramienta | Para qué la usamos | Acceso | Para aprender |", "|---|---|---|---|"]
            lines += [f"| [{i['name']}]({i['url']}) | {i['what']} {i['used_for']} | {i['access']} | {_learn(i)} |"
                      for i in group]
        elif kind == "open_source":
            lines += ["| Proyecto | Licencia | Para qué | Dónde | Para aprender |", "|---|---|---|---|---|"]
            lines += [f"| [{i['name']}]({i['url']}) | {i['license']} | {i['used_for']} | "
                      f"{', '.join(i.get('where', []))} | {_learn(i)} |" for i in group]
        else:
            lines += ["| Fuente | Para qué | Dónde |", "|---|---|---|"]
            lines += [f"| [{i['name']}]({i['url']}) | {i['used_for']} | {', '.join(i.get('where', []))} |"
                      for i in group]
        lines.append("")
    return "\n".join(lines)


def _learn(item):
    return f"[enlace]({item['learn']})" if item.get("learn") else ""


def render_plan(catalog, handle, role_id, extra_grants=()):
    """Checklist personal en Markdown. Sin nombre a propósito: el plan puede compartirse o guardarse sin datos personales."""
    _check_handle(handle)
    role = catalog.role(role_id)
    grants = catalog.grants_for(role_id, extra_grants)
    steps = catalog.steps_for(role_id, grants)
    lines = [f"# Onboarding de {handle}: {role['name']}", "", role["summary"], "",
             f"Antes de nada lee [las reglas de oro]({RULES_URL}). Marca cada casilla cuando termines el paso y avisa al "
             "fundador para que quede registrado en el diario.", "",
             "## Tus accesos", ""]
    lines += [f"- `{g}`" for g in grants]
    lines += ["", "Nunca tendrás acceso a Binance ni podrás autorizar o vetar operaciones: eso es solo del fundador.", ""]
    for when, heading in WHEN.items():
        group = [s for s in steps if s["when"] == when]
        if not group:
            continue
        lines += [f"## {heading}", ""]
        for step in group:
            lines.append(f"- [ ] **{step['title']}** (`{step['id']}`). {_fill(step['detail'], handle, role_id)}")
            if step.get("command"):
                lines.append(f"  ```\n  {_fill(step['command'], handle, role_id)}\n  ```")
        lines.append("")
    lines += ["## Tu mapa de herramientas", "", f"`python -m team stack --role {role_id}` te lo muestra completo.", ""]
    # Solo los repos privados a los que tiene acceso, y lo que se usa en los repos que ve.
    repos = {i["id"] for i in catalog.items if i["kind"] == "repo"
             and (i.get("visibility") == "public" or grant_satisfies(grants, f"github:{i['id']}"))}
    visible = [i for i in catalog.items_for(role_id)
               if (i["kind"] != "repo" or i["id"] in repos) and (not i.get("where") or repos & set(i["where"]))]
    for kind, heading in KINDS.items():
        names = [i["name"] for i in visible if i["kind"] == kind]
        if names:
            lines.append(f"- **{heading}:** {', '.join(names)}")
    return "\n".join(lines) + "\n"


def _fill(text, handle, role_id):
    return text.replace("{handle}", handle).replace("{role}", role_id)


def join_sql(catalog, handle, display_name, role_id, note, github_login=None, extra_grants=()):
    _check_handle(handle)
    if not display_name or len(display_name) > 80:
        raise ValueError("El nombre debe tener entre 1 y 80 caracteres")
    if github_login is not None and not GITHUB_LOGIN.match(github_login):
        raise ValueError(f"Usuario de GitHub no válido: {github_login!r}")
    grants = catalog.grants_for(role_id, extra_grants)
    lines = [f"-- Alta de {handle} como {role_id}. Decisión del fundador, citada en note.", "begin;",
             "insert into public.team_members (id, display_name, github_login) values "
             f"({_lit(handle)}, {_lit(display_name)}, {_lit(github_login)}) on conflict (id) do nothing;",
             _event(handle, "JOINED", "user", note),
             _event(handle, "ROLE_SET", "user", note, role=role_id)]
    lines += [_event(handle, "ACCESS_GRANTED", "user", note, resource=g) for g in grants]
    lines.append("commit;")
    if "supabase:finance-tool:read" in grants:
        lines += ["", *personal_role_sql(handle)]
    return "\n".join(lines) + "\n"


def personal_role_sql(handle):
    _check_handle(handle)
    role = f"team_{handle}"
    return [f"-- Rol personal de solo lectura: hereda dashboard_reader (lee el diario, no escribe nada) y se puede",
            "-- desactivar sin tocar a nadie más. La contraseña la pones tú en el SQL Editor y la entregas en persona o",
            "-- por un gestor de contraseñas, nunca por chat ni en el repositorio:",
            f"--   alter role {role} with login password '...';",
            f"create role {role} nologin in role dashboard_reader;",
            f"alter role {role} set default_transaction_read_only = on;",
            f"alter role {role} set statement_timeout = '10s';"]


def role_sql(handle, role_id, catalog, note):
    catalog.role(role_id)
    return _event(handle, "ROLE_SET", "user", note, role=role_id) + "\n"


def grant_sql(handle, resource, note, revoke=False, decided_by="user"):
    if not RESOURCE.match(resource):
        raise ValueError(f"Recurso no válido: {resource!r} (formato servicio:proyecto:nivel)")
    if not revoke and resource_forbidden(resource):
        raise ValueError(f"{resource!r} no se puede conceder a un miembro del equipo (ver docs/team/README.md)")
    kind = "ACCESS_REVOKED" if revoke else "ACCESS_GRANTED"
    return _event(handle, kind, "user" if not revoke else decided_by, note, resource=resource) + "\n"


def step_sql(catalog, handle, step_id, note, decided_by="member"):
    if not STEP_ID.match(step_id) or step_id not in {s["id"] for s in catalog.steps}:
        raise ValueError(f"Paso desconocido: {step_id!r}")
    return _event(handle, "STEP_DONE", decided_by, note, step_id=step_id) + "\n"


def leave_sql(handle, note):
    _check_handle(handle)
    return "\n".join([
        f"-- Baja de {handle}. 1) Registra la baja y desactiva su rol de base (si lo tiene).",
        _event(handle, "LEFT", "user", note),
        f"do $$ begin if exists (select 1 from pg_roles where rolname = 'team_{handle}') then",
        f"  alter role team_{handle} nologin; end if; end $$;",
        "-- 2) Quita sus accesos fuera de la base (GitHub, Vercel...). Los pendientes salen de:",
        f"select resource from public.v_team_offboarding_pending where member_id = {_lit(handle)};",
        "-- 3) Cuando los hayas quitado, regístralo. La vista debe quedar vacía:",
        "insert into public.team_member_events (member_id, kind, resource, decided_by, note)",
        f"select member_id, 'ACCESS_REVOKED', resource, 'user', {_lit('offboarding: ' + note)}",
        f"from public.v_team_offboarding_pending where member_id = {_lit(handle)};",
    ]) + "\n"


def _event(handle, kind, decided_by, note, role=None, resource=None, step_id=None):
    _check_handle(handle)
    if decided_by not in DECIDERS:
        raise ValueError(f"decided_by debe ser uno de {DECIDERS}")
    if not note or len(note) > 1000:
        raise ValueError("La nota (cita de la decisión) debe tener entre 1 y 1000 caracteres")
    return ("insert into public.team_member_events (member_id, kind, role, resource, step_id, decided_by, note) values "
            f"({_lit(handle)}, {_lit(kind)}, {_lit(role)}, {_lit(resource)}, {_lit(step_id)}, {_lit(decided_by)}, "
            f"{_lit(note)});")


def _check_handle(handle):
    if not HANDLE.match(handle or ""):
        raise ValueError(f"Handle no válido: {handle!r} (minúsculas, números y _, empieza por letra, 2-31 caracteres)")


def _lit(value):
    if value is None:
        return "null"
    if "\x00" in value:
        raise ValueError("Texto con carácter nulo")
    return "'" + value.replace("'", "''") + "'"
