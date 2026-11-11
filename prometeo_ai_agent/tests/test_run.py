from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged

from .common import AiAgentCase

RESULT = {"input_tokens": 1_000_000, "output_tokens": 500_000, "tool_calls": 2}


@tagged("post_install", "-at_install")
class TestRun(AiAgentCase):

    def setUp(self):
        super().setUp()
        self.Run = self.env["prometeo.ai.run"]
        self.Run.sudo().search([]).unlink()

    def _set_cap(self, value):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.monthly_cap_usd", value)

    def test_log_computes_cost(self):
        run = self.Run._log("chat", self.ai_model, RESULT, user=self.agent_user, status="done")
        self.assertAlmostEqual(run.cost, 2.0)
        self.assertEqual((run.tool_calls, run.provider_type, run.model_name), (2, "openai", "gpt-test"))
        self.assertTrue(run.price_known)

    def test_unpriced_model_does_not_count_for_cap(self):
        self.ai_model.price_known = False
        run = self.Run._log("chat", self.ai_model, RESULT, user=self.agent_user, status="done")
        self.assertEqual(run.cost, 0.0)
        self.assertFalse(run.price_known)

    def test_cap_reached(self):
        self._set_cap(1.0)
        self.assertFalse(self.Run._cap_reached())
        self.Run._log("chat", self.ai_model, RESULT, user=self.agent_user, status="done")
        self.assertTrue(self.Run._cap_reached())
        self._set_cap(100)
        self.assertFalse(self.Run._cap_reached())

    def test_month_cost_ignores_previous_month(self):
        old = self.Run._log("chat", self.ai_model, RESULT, user=self.agent_user, status="done")
        self.env.cr.execute("UPDATE prometeo_ai_run SET create_date = %s WHERE id = %s",
                            (datetime.now() - timedelta(days=45), old.id))
        self.Run.invalidate_model()
        self.Run._log("chat", self.ai_model, {"input_tokens": 1_000_000, "output_tokens": 0, "tool_calls": 0},
                      user=self.agent_user, status="done")
        self.assertAlmostEqual(self.Run._month_cost(), 1.0)

    def test_agent_user_cannot_read_runs(self):
        from odoo.exceptions import AccessError
        run = self.Run._log("chat", self.ai_model, RESULT, user=self.agent_user, status="done")
        with self.assertRaises(AccessError):
            run.with_user(self.agent_user).read(["cost"])


@tagged("post_install", "-at_install")
class TestUsageSummary(AiAgentCase):

    def setUp(self):
        super().setUp()
        self.Run = self.env["prometeo.ai.run"].sudo()
        self.Run.search([]).unlink()
        self.routine = self.env["prometeo.ai.routine"].create({"name": "Rutina A", "prompt": "x"})
        now = fields.Datetime.now()
        self.year, self.month = now.year, now.month
        tokens = lambda inp: {"input_tokens": inp, "output_tokens": 0, "tool_calls": 0}  # noqa: E731
        self.Run._log("routine", self.ai_model, tokens(500_000), routine=self.routine, status="done")
        self.Run._log("routine", self.ai_model, tokens(1_500_000), routine=self.routine, status="done")
        self.Run._log("chat", self.ai_model, tokens(200_000), user=self.agent_user, status="done")
        unpriced = self.env["prometeo.ai.model"].create({"provider_id": self.provider.id, "name": "sin-precio",
                                                         "active": True})
        self.Run._log("chat", unpriced, tokens(100), user=self.agent_user, status="done")

    def test_usage_summary_groups_and_sorts(self):
        s = self.env["prometeo.ai.run"].with_user(self.admin_user).get_usage_summary(self.year, self.month)
        self.assertAlmostEqual(s["cost"], 2.2)
        self.assertEqual([r["name"] for r in s["by_routine"]][:2], ["Rutina A", "Chat"])
        self.assertEqual(s["by_routine"][0]["runs"], 2)
        self.assertEqual(s["by_routine"][0]["input_tokens"], 2_000_000)
        self.assertEqual(s["unpriced_runs"], 1)
        self.assertEqual(s["by_model"][0]["name"], self.ai_model.display_name)

    def test_usage_summary_admin_only(self):
        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            self.env["prometeo.ai.run"].with_user(self.agent_user).get_usage_summary(self.year, self.month)

    def test_usage_summary_other_month_empty(self):
        s = self.env["prometeo.ai.run"].with_user(self.admin_user).get_usage_summary(self.year - 1, self.month)
        self.assertEqual((s["cost"], s["by_routine"], s["by_model"], s["unpriced_runs"]), (0.0, [], [], 0))



@tagged("post_install", "-at_install")
class TestQuota(AiAgentCase):

    def setUp(self):
        super().setUp()
        self.Run = self.env["prometeo.ai.run"].sudo()
        self.Run.search([]).unlink()
        self.env["ir.config_parameter"].sudo().search([("key", "=", "prometeo_ai_agent.monthly_cap_usd")]).unlink()

    def test_default_cap_is_5_usd(self):
        self.Run._log("chat", self.ai_model, {"input_tokens": 4_000_000, "output_tokens": 0}, status="done")
        self.assertFalse(self.Run._cap_reached())
        self.Run._log("chat", self.ai_model, {"input_tokens": 1_000_000, "output_tokens": 0}, status="done")
        self.assertTrue(self.Run._cap_reached())

    def test_quota_status_shows_percent_without_money(self):
        self.Run._log("chat", self.ai_model, {"input_tokens": 1_750_000, "output_tokens": 0}, status="done")
        status = self.env["prometeo.ai.run"].with_user(self.agent_user).get_quota_status()
        self.assertEqual(status, {"percent": 35, "level": "ok"})

    def test_chat_has_no_usage_entry_and_settings_has_it(self):
        import os
        base = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(base, "static/src/xml/chat_action.xml")) as f:
            chat = f.read()
        self.assertNotIn("action_ai_usage", chat)
        self.assertIn("get_quota_status", open(os.path.join(base, "static/src/js/chat_action.js")).read())
        self.assertIn("action_ai_open_usage", self.env["res.config.settings"].get_view(view_type="form")["arch"])
