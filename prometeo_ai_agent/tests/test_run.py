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
        self._set_cap(0)
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
