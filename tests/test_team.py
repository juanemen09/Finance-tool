import contextlib
import io
import re
import unittest
from pathlib import Path

from team import doctor, onboarding
from team.__main__ import main
from team.catalog import Catalog, resource_forbidden

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "supabase" / "migrations" / "20260927010000_team_members.sql"


def mini_catalog(**overrides):
    items = [{"id": "pub", "kind": "repo", "name": "Pub", "url": "u", "visibility": "public", "what": "w",
              "stack": "s", "start": "x", "roles": []},
             {"id": "priv", "kind": "repo", "name": "Priv", "url": "u", "visibility": "private", "what": "w",
              "stack": "s", "start": "x", "roles": ["dev"]},
             {"id": "lib", "kind": "open_source", "name": "Lib", "url": "u", "license": "MIT", "used_for": "x",
              "where": ["priv"], "roles": []}]
    roles = [{"id": "dev", "name": "Dev", "summary": "s", "grants": ["github:pub:write"],
              "optional_grants": ["github:priv:read"]}]
    steps = [{"id": "uno", "when": "dia-1", "title": "Uno", "detail": "hola {handle}", "roles": []},
             {"id": "priv-demo", "when": "semana-2", "title": "Demo", "detail": "d", "roles": ["dev"],
              "requires_grant": "github:priv"}]
    data = {"items": items, "roles": roles, "steps": steps}
    data.update(overrides)
    return Catalog(data["items"], data["roles"], data["steps"])


class CatalogTest(unittest.TestCase):
    def test_real_config_is_valid(self):
        catalog = Catalog.load()
        self.assertEqual(set(catalog.roles), {"observer", "analyst", "developer"})
        self.assertIn("finance-tool", {i["id"] for i in catalog.items})

    def test_role_ids_match_database_check(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        allowed = set(re.search(r"role text check \(role in \(([^)]*)\)\)", sql).group(1).replace("'", "")
                      .replace(" ", "").split(","))
        self.assertEqual(allowed, set(Catalog.load().roles))

    def test_forbidden_resources_mirror_the_database(self):
        for resource in ("binance:read", "binance:trading", "journal:veto", "supabase:finance-tool:write"):
            self.assertTrue(resource_forbidden(resource), resource)
        for resource in ("supabase:finance-tool:read", "github:finance-tool:write", "dashboard:finance-tool"):
            self.assertFalse(resource_forbidden(resource), resource)

    def test_rejects_forbidden_grant_in_config(self):
        roles = [{"id": "dev", "name": "D", "summary": "s", "grants": ["binance:trading"], "optional_grants": []}]
        with self.assertRaises(ValueError):
            mini_catalog(roles=roles)

    def test_rejects_unknown_role_and_duplicate_ids(self):
        with self.assertRaises(ValueError):
            mini_catalog(steps=[{"id": "x", "when": "dia-1", "title": "t", "detail": "d", "roles": ["nadie"]}])
        catalog = mini_catalog()
        with self.assertRaises(ValueError):
            Catalog(catalog.items + catalog.items[:1], list(catalog.roles.values()), catalog.steps)

    def test_optional_grants_are_the_only_extras(self):
        catalog = mini_catalog()
        self.assertEqual(catalog.grants_for("dev", ["github:priv:read"]), ["github:pub:write", "github:priv:read"])
        with self.assertRaises(ValueError):
            catalog.grants_for("dev", ["github:otro:write"])


class PlanTest(unittest.TestCase):
    def test_private_repo_and_its_steps_only_with_access(self):
        catalog = mini_catalog()
        without = onboarding.render_plan(catalog, "ana_m", "dev")
        self.assertNotIn("Priv", without)
        self.assertNotIn("Lib", without)
        self.assertNotIn("priv-demo", without)
        with_access = onboarding.render_plan(catalog, "ana_m", "dev", ["github:priv:read"])
        self.assertIn("Priv", with_access)
        self.assertIn("Lib", with_access)
        self.assertIn("priv-demo", with_access)
        self.assertIn("hola ana_m", with_access)

    def test_real_plans_render_for_every_role(self):
        catalog = Catalog.load()
        for role in catalog.roles:
            plan = onboarding.render_plan(catalog, "primo_a", role)
            self.assertIn("- [ ] **Prepara tu entorno local**", plan)
            self.assertNotIn("{handle}", plan)

    def test_rejects_bad_handle(self):
        with self.assertRaises(ValueError):
            onboarding.render_plan(mini_catalog(), "Ana M", "dev")

    def test_private_overlay_never_reaches_the_public_doc(self):
        catalog = mini_catalog()
        catalog.items.append({"id": "secreto", "kind": "app", "name": "Secreto", "url": "u", "what": "w",
                              "used_for": "x", "access": "a", "roles": [], "private": True})
        self.assertNotIn("Secreto", onboarding.render_stack_markdown(catalog))
        self.assertIn("Secreto", onboarding.render_stack_markdown(catalog, include_private=True))

    def test_stack_doc_is_in_sync(self):
        expected = onboarding.render_stack_markdown(Catalog.load()) + "\n"
        actual = (ROOT / "docs" / "team" / "stack.md").read_text(encoding="utf-8")
        self.assertEqual(actual, expected, "Regenera: python -m team stack --markdown > docs/team/stack.md")


class SqlTest(unittest.TestCase):
    def test_join_quotes_text_and_grants_role_accesses(self):
        sql = onboarding.join_sql(Catalog.load(), "primo_a", "O'Neil'); drop table x; --", "analyst",
                                  "Juan: 'sí'")
        self.assertIn("'O''Neil''); drop table x; --'", sql)
        self.assertIn("'Juan: ''sí'''", sql)
        for grant in ("github:finance-tool:read", "supabase:finance-tool:read", "dashboard:finance-tool"):
            self.assertIn(f"'ACCESS_GRANTED', null, '{grant}'", sql)
        self.assertIn("create role team_primo_a nologin in role dashboard_reader;", sql)
        self.assertNotIn("password '", sql.replace("password '...'", ""))

    def test_observer_gets_no_database_role(self):
        sql = onboarding.join_sql(Catalog.load(), "primo_b", "B", "observer", "ok")
        self.assertNotIn("create role", sql)

    def test_cannot_grant_forbidden_but_can_revoke_it(self):
        with self.assertRaises(ValueError):
            onboarding.grant_sql("primo_a", "binance:trading", "x")
        self.assertIn("ACCESS_REVOKED", onboarding.grant_sql("primo_a", "binance:trading", "x", revoke=True))

    def test_step_must_exist(self):
        catalog = Catalog.load()
        self.assertIn("'STEP_DONE'", onboarding.step_sql(catalog, "primo_a", "pruebas", "hecho"))
        with self.assertRaises(ValueError):
            onboarding.step_sql(catalog, "primo_a", "no-existe", "x")

    def test_leave_disables_role_and_lists_pending(self):
        sql = onboarding.leave_sql("primo_a", "baja")
        self.assertIn("'LEFT'", sql)
        self.assertIn("alter role team_primo_a nologin", sql)
        self.assertIn("v_team_offboarding_pending", sql)

    def test_cli_reports_errors_without_traceback(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = main(["sql", "grant", "--handle", "primo_a", "--resource", "journal:veto", "--note", "x"])
        self.assertEqual(code, 2)
        self.assertIn("no se puede conceder", err.getvalue())


class DoctorTest(unittest.TestCase):
    def run_checks(self, env):
        return {name: (status, message) for status, name, message in doctor.run_checks(
            env=env, python=(3, 11), which=lambda tool: "/usr/bin/" + tool, git_config=lambda key: "x")}

    def test_personal_role_ok_shared_role_warns(self):
        url = "postgresql://team_ana_m.ref:SECRETO@host:5432/postgres"
        checks = self.run_checks({"DASHBOARD_DATABASE_URL": url})
        self.assertEqual(checks["Centro de mando"][0], doctor.OK)
        self.assertNotIn("SECRETO", doctor.render(doctor.run_checks(
            env={"DASHBOARD_DATABASE_URL": url}, python=(3, 11), which=lambda t: None, git_config=lambda k: None)))
        shared = self.run_checks({"DASHBOARD_DATABASE_URL": "postgresql://dashboard_reader.ref:p@h/postgres"})
        self.assertEqual(shared["Centro de mando"][0], doctor.WARN)

    def test_agent_credentials_fail(self):
        checks = self.run_checks({"INGEST_DATABASE_URL": "postgresql://lab_ingest.ref:p@h/postgres"})
        self.assertEqual(checks["INGEST_DATABASE_URL"][0], doctor.FAIL)
        self.assertNotIn("lab_ingest.ref:p", checks["INGEST_DATABASE_URL"][1])

    def test_old_python_fails(self):
        checks = {name: status for status, name, _ in doctor.run_checks(
            env={}, python=(3, 9), which=lambda t: None, git_config=lambda k: None)}
        self.assertEqual(checks["Python"], doctor.FAIL)


if __name__ == "__main__":
    unittest.main()
