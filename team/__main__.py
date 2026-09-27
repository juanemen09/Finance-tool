"""Módulo de equipo: onboarding, inventario del stack y registro de personas en el diario.

  python -m team roles                                   roles disponibles y sus accesos
  python -m team stack [--role analyst] [--markdown]     repos, aplicaciones, open source y fuentes de datos [--private]
  python -m team plan --handle primo_a --role analyst    checklist personal (Markdown) [--grant ...] [--out archivo]
  python -m team doctor                                  comprueba tu entorno local

  SQL para el diario (lo imprime; lo ejecuta el fundador o su agente con el conector de Supabase):
  python -m team sql join  --handle primo_a --name "Nombre" --role analyst --note "cita del fundador" [--github x] [--grant ...]
  python -m team sql step  --handle primo_a --step entorno-local --note "..." [--by member]
  python -m team sql role  --handle primo_a --role developer --note "..."
  python -m team sql grant --handle primo_a --resource github:praxiguard:read --note "..." [--revoke]
  python -m team sql leave --handle primo_a --note "..."
"""
import argparse
import sys
from pathlib import Path

from team import doctor, onboarding
from team.catalog import Catalog


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m team", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("roles")
    stack = sub.add_parser("stack")
    stack.add_argument("--role")
    stack.add_argument("--markdown", action="store_true")
    stack.add_argument("--private", action="store_true", help="Incluye stack.private.json (nunca para docs/team/stack.md)")
    plan = sub.add_parser("plan")
    plan.add_argument("--handle", required=True)
    plan.add_argument("--role", required=True)
    plan.add_argument("--grant", action="append", default=[])
    plan.add_argument("--out")
    sub.add_parser("doctor")

    sql = sub.add_parser("sql").add_subparsers(dest="action", required=True)
    join = sql.add_parser("join")
    join.add_argument("--handle", required=True)
    join.add_argument("--name", required=True)
    join.add_argument("--role", required=True)
    join.add_argument("--github")
    join.add_argument("--grant", action="append", default=[])
    step = sql.add_parser("step")
    step.add_argument("--handle", required=True)
    step.add_argument("--step", required=True)
    step.add_argument("--by", default="member", choices=onboarding.DECIDERS)
    role = sql.add_parser("role")
    role.add_argument("--handle", required=True)
    role.add_argument("--role", required=True)
    grant = sql.add_parser("grant")
    grant.add_argument("--handle", required=True)
    grant.add_argument("--resource", required=True)
    grant.add_argument("--revoke", action="store_true")
    leave = sql.add_parser("leave")
    leave.add_argument("--handle", required=True)
    for action in (join, step, role, grant, leave):
        action.add_argument("--note", required=True, help="Cita literal de la decisión o del aviso")

    args = parser.parse_args(argv)
    try:
        return _run(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


def _run(args):
    if args.command == "doctor":
        checks = doctor.run_checks()
        print(doctor.render(checks))
        return 1 if any(status == doctor.FAIL for status, _, _ in checks) else 0

    catalog = Catalog.load()
    if args.command == "roles":
        for role in catalog.roles.values():
            print(f"{role['id']:10} {role['name']}\n           {role['summary']}")
            print(f"           accesos: {', '.join(role['grants'])}")
            if role["optional_grants"]:
                print(f"           opcionales (--grant): {', '.join(role['optional_grants'])}")
        return 0
    if args.command == "stack":
        if args.markdown:
            print(onboarding.render_stack_markdown(catalog, args.role, args.private))
        else:
            for item in catalog.items_for(args.role):
                print(f"[{item['kind']:11}] {item['name']}  {item['url']}")
        return 0
    if args.command == "plan":
        text = onboarding.render_plan(catalog, args.handle, args.role, args.grant)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"Plan escrito en {args.out}", file=sys.stderr)
        else:
            print(text, end="")
        return 0

    if args.action == "join":
        out = onboarding.join_sql(catalog, args.handle, args.name, args.role, args.note, args.github, args.grant)
    elif args.action == "step":
        out = onboarding.step_sql(catalog, args.handle, args.step, args.note, args.by)
    elif args.action == "role":
        out = onboarding.role_sql(args.handle, args.role, catalog, args.note)
    elif args.action == "grant":
        out = onboarding.grant_sql(args.handle, args.resource, args.note, revoke=args.revoke)
    else:
        out = onboarding.leave_sql(args.handle, args.note)
    print(out, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
