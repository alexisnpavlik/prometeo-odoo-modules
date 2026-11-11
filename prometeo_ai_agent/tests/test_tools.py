import json

from odoo.tests import tagged

from odoo.addons.prometeo_ai_agent.agent import tools

from .common import AiAgentCase


@tagged("post_install", "-at_install")
class TestTools(AiAgentCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partners = cls.env["res.partner"].create([{"name": "AI Tool P%s" % i, "color": i + 1} for i in range(3)])
        cls.other_company = cls.env["res.company"].create({"name": "AI Otra Empresa"})
        cls.hidden_partner = cls.env["res.partner"].create({"name": "AI Oculto", "company_id": cls.other_company.id})

    def setUp(self):
        super().setUp()
        self.uenv = self.env(user=self.agent_user)
        self.ctx = tools.new_context()

    def call(self, name, **arguments):
        return json.loads(tools.execute_tool(self.uenv, self.ctx, name, arguments))

    def set_param(self, key, value):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent." + key, value)

    def ids_domain(self, records):
        return json.dumps([["id", "in", records.ids]])

    def test_search_read_records_seen_ids(self):
        out = self.call("search_read", model="res.partner", domain=self.ids_domain(self.partners), fields=["name"])
        self.assertEqual({r["id"] for r in out["records"]}, set(self.partners.ids))
        self.assertTrue(set(self.partners.ids) <= self.ctx["seen"]["res.partner"])
        self.assertIn(json.dumps([["id", "in", self.partners.ids]], sort_keys=True), self.ctx["domains"]["res.partner"])

    def test_limit_is_capped(self):
        self.set_param("max_records", 2)
        out = self.call("search_read", model="res.partner", domain=self.ids_domain(self.partners), fields=["name"], limit=50)
        self.assertEqual(len(out["records"]), 2)

    def test_blocked_model_rejected(self):
        out = self.call("search_read", model="ir.config_parameter", domain="[]", fields=["key"])
        self.assertIn("error", out)

    def test_domain_into_blocked_model_rejected(self):
        out = self.call("search_count", model="res.partner", domain=json.dumps([["message_ids.body", "ilike", "x"]]))
        self.assertIn("error", out)

    def test_domain_on_secret_field_rejected(self):
        out = self.call("search_count", model="res.partner", domain=json.dumps([["user_ids.password", "like", "a%"]]))
        self.assertIn("error", out)

    def test_res_users_only_whitelisted_fields(self):
        self.assertIn("error", self.call("search_read", model="res.users", domain="[]", fields=["name", "email"]))
        self.assertIn("error", self.call("search_count", model="res.users", domain=json.dumps([["signature", "ilike", "x"]])))
        names = {f["name"] for f in self.call("get_fields", model="res.users")["fields"]}
        self.assertTrue(names <= {"id", "name", "login", "company_id", "display_name"})
        self.assertIn("login", names)

    def test_binary_field_rejected(self):
        out = self.call("search_read", model="res.partner", domain="[]", fields=["image_1920"])
        self.assertIn("error", out)

    def test_order_on_blocked_field_rejected(self):
        out = self.call("search_read", model="res.partner", domain="[]", fields=["name"], order="user_ids.password")
        self.assertIn("error", out)

    def test_unknown_field_returns_error_and_cursor_survives(self):
        out = self.call("search_read", model="res.partner", domain="[]", fields=["no_existe"])
        self.assertIn("error", out)
        out = self.call("search_count", model="res.partner", domain=json.dumps([["no_existe", "=", 1]]))
        self.assertIn("error", out)
        self.assertGreater(self.env["res.partner"].search_count([]), 0)

    def test_malformed_domain_returns_error(self):
        self.assertIn("error", self.call("search_count", model="res.partner", domain="no es json"))
        self.assertIn("error", self.call("search_count", model="res.partner", domain="[[1,2]]"))
        self.assertIn("error", self.call("search_count", model="res.partner", domain='{"a": 1}'))

    def test_record_rules_apply(self):
        out = self.call("search_count", model="res.partner", domain=self.ids_domain(self.hidden_partner))
        self.assertEqual(out["count"], 0)
        self.assertEqual(self.env["res.partner"].search_count([("id", "=", self.hidden_partner.id)]), 1)

    def test_read_group_sums_and_records_domain(self):
        out = self.call("read_group", model="res.partner", domain=self.ids_domain(self.partners),
                        groupby=[], aggregates=["color:sum", "id:count"])
        self.assertIn("groups", out, out)
        self.assertEqual(out["groups"][0]["color:sum"], 6)
        self.assertEqual(out["groups"][0]["id:count"], 3)
        self.assertTrue(self.ctx["domains"]["res.partner"])

    def test_read_group_rejects_bad_aggregate(self):
        out = self.call("read_group", model="res.partner", domain="[]", groupby=[], aggregates=["color:drop"])
        self.assertIn("error", out)

    def test_result_truncated(self):
        self.set_param("max_result_chars", 200)
        raw = tools.execute_tool(self.uenv, self.ctx, "search_read",
                                 {"model": "res.partner", "domain": "[]", "fields": ["name", "display_name"], "limit": 50})
        self.assertTrue(raw.endswith("...[recortado]"))
        self.assertLessEqual(len(raw), 200 + len("...[recortado]"))

    def test_list_models_excludes_blocked_and_unreadable(self):
        names = {m["model"] for m in self.call("list_models")["models"]}
        self.assertIn("res.partner", names)
        self.assertNotIn("ir.config_parameter", names)
        self.assertNotIn("prometeo.ai.provider", names)
        found = {m["model"] for m in self.call("list_models", search="partner")["models"]}
        self.assertIn("res.partner", found)

    def test_unknown_tool(self):
        self.assertIn("error", self.call("borrar_todo", model="res.partner"))

    def test_any_subdomain_is_validated(self):
        domain = json.dumps([["user_ids", "any", [["password", "like", "a%"]]]])
        self.assertIn("error", self.call("search_count", model="res.partner", domain=domain))
        domain = json.dumps([["message_follower_ids", "any", [["partner_id.user_ids.password", "=", "x"]]]])
        self.assertIn("error", self.call("search_count", model="res.partner", domain=domain))

    def test_read_group_having_order_limit_and_total(self):
        out = self.call("read_group", model="res.partner", domain=self.ids_domain(self.partners),
                        groupby=["id"], aggregates=["color:sum"], having=json.dumps([["color:sum", ">=", 2]]),
                        order="color:sum desc", limit=1)
        self.assertEqual(out["total_groups"], 2)
        self.assertEqual(len(out["groups"]), 1)
        self.assertEqual(out["groups"][0]["color:sum"], 3)

    def test_read_group_having_rejects_unknown_aggregate(self):
        out = self.call("read_group", model="res.partner", domain="[]", groupby=["id"], aggregates=["color:sum"],
                        having=json.dumps([["password:sum", ">", 0]]))
        self.assertIn("error", out)
