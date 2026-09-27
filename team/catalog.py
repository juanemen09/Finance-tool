"""Catálogo del equipo: inventario de herramientas (config/team/stack.json) y roles con sus pasos (roles.json).

config/team/stack.private.json, si existe, se suma al inventario. Git lo ignora: ahí van los detalles internos de
los repos privados, porque este repositorio es público.
"""
import json
import re
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "team"
KINDS = {"repo": "Repositorios", "app": "Aplicaciones y servicios", "open_source": "Open source",
         "data_source": "Fuentes de datos"}
WHEN = {"dia-1": "Día 1", "semana-1": "Semana 1", "semana-2": "Semana 2"}
HANDLE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
RESOURCE = re.compile(r"^[a-z][a-z0-9_]*(:[a-z0-9_.-]+)+$")
STEP_ID = re.compile(r"^[a-z][a-z0-9-]*$")
GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](-?[A-Za-z0-9]){0,38}$")


def resource_forbidden(resource):
    """Mismo criterio que public.team_resource_forbidden: Binance es de los agentes, el diario lo escriben ellos y las
    decisiones (autorizar, vetar, límites, LIVE_ELIGIBLE) son del fundador."""
    return (resource.startswith("binance:") or resource.startswith("journal:")
            or (resource.startswith("supabase:finance-tool:") and resource != "supabase:finance-tool:read"))


def grant_satisfies(grants, requirement):
    return any(g == requirement or g.startswith(requirement + ":") for g in grants)


class Catalog:
    def __init__(self, items, roles, steps):
        self.items, self.roles, self.steps = items, {r["id"]: r for r in roles}, steps
        self.validate()

    @classmethod
    def load(cls, config_dir=CONFIG_DIR):
        config_dir = Path(config_dir)
        items = json.loads((config_dir / "stack.json").read_text(encoding="utf-8"))["items"]
        private = config_dir / "stack.private.json"
        if private.exists():
            items = items + [dict(i, private=True) for i in json.loads(private.read_text(encoding="utf-8"))["items"]]
        roles = json.loads((config_dir / "roles.json").read_text(encoding="utf-8"))
        return cls(items, roles["roles"], roles["steps"])

    def validate(self):
        ids = [i["id"] for i in self.items]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"Ids repetidos en el inventario: {duplicated}")
        repos = {i["id"] for i in self.items if i["kind"] == "repo"}
        for item in self.items:
            if item["kind"] not in KINDS:
                raise ValueError(f"{item['id']}: tipo desconocido {item['kind']!r}")
            self._check_roles(item["id"], item.get("roles", []))
            unknown = set(item.get("where", [])) - repos
            if unknown:
                raise ValueError(f"{item['id']}: repos desconocidos en where: {sorted(unknown)}")
        for role in self.roles.values():
            for grant in role["grants"] + role["optional_grants"]:
                if not RESOURCE.match(grant) or resource_forbidden(grant):
                    raise ValueError(f"{role['id']}: acceso no válido o prohibido {grant!r}")
        step_ids = [s["id"] for s in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Pasos de onboarding repetidos")
        for step in self.steps:
            if not STEP_ID.match(step["id"]) or step["when"] not in WHEN:
                raise ValueError(f"Paso no válido: {step['id']!r}")
            self._check_roles(step["id"], step.get("roles", []))

    def _check_roles(self, owner, roles):
        unknown = set(roles) - set(self.roles)
        if unknown:
            raise ValueError(f"{owner}: roles desconocidos {sorted(unknown)}")

    def role(self, role_id):
        if role_id not in self.roles:
            raise ValueError(f"Rol desconocido {role_id!r}. Roles: {', '.join(self.roles)}")
        return self.roles[role_id]

    def items_for(self, role_id=None, include_private=True):
        if role_id is not None:
            self.role(role_id)
        return [i for i in self.items if (role_id is None or not i.get("roles") or role_id in i["roles"])
                and (include_private or not i.get("private"))]

    def grants_for(self, role_id, extra=()):
        role = self.role(role_id)
        for grant in extra:
            if grant not in role["optional_grants"]:
                raise ValueError(f"{grant!r} no es un acceso opcional del rol {role_id}. "
                                 f"Opcionales: {', '.join(role['optional_grants']) or 'ninguno'}")
        return list(dict.fromkeys(role["grants"] + list(extra)))

    def steps_for(self, role_id, grants):
        self.role(role_id)
        return [s for s in self.steps
                if (not s.get("roles") or role_id in s["roles"])
                and (not s.get("requires_grant") or grant_satisfies(grants, s["requires_grant"]))]
