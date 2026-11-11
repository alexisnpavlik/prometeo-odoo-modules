import json
from unittest.mock import patch

import psycopg2

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.prometeo_ai_agent import llm
from odoo.addons.prometeo_ai_agent.agent import guard, tools

from .common import AiAgentCase, llm_text, llm_tool
from .test_llm import USER, fake_response


@tagged("post_install", "-at_install")
class TestReviewFixes(AiAgentCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({"name": "AI Fix Partner"})
        self.routine = self.env["prometeo.ai.routine"].create({
            "name": "R", "prompt": "x", "run_as_user_id": self.admin_user.id,
            "recipient_ids": [(6, 0, [self.agent_user.id])]})

    # 1
    def test_user_cannot_run_or_resume_routine(self):
        with self.assertRaises(AccessError):
            self.routine.with_user(self.agent_user).action_run_now()
        with self.assertRaises(AccessError):
            self.routine.with_user(self.agent_user).action_resume()

    # 2
    def test_mail_mail_and_key_fields_blocked(self):
        uenv = self.env(user=self.admin_user)
        out = json.loads(tools.execute_tool(uenv, tools.new_context(), "search_read",
                                            {"model": "mail.mail", "domain": "[]", "fields": ["body_html"]}))
        self.assertIn("error", out)
        for name in ("adyen_hmac_key", "key", "webhook_signature", "credential_id"):
            self.assertTrue(guard.SECRET_FIELD_RE.search(name), name)

    # 3
    def test_agent_admin_cannot_run_as_other_user(self):
        with self.assertRaises(ValidationError):
            self.env["prometeo.ai.routine"].with_user(self.admin_user).create(
                {"name": "x", "run_as_user_id": self.env.ref("base.user_admin").id})

    # 4
    def test_only_one_open_alert_per_key(self):
        Alert = self.env["prometeo.ai.alert"].sudo()
        vals = {"name": "a", "dedup_key": "k", "routine_id": self.routine.id}
        Alert.create(vals)
        with mute_logger("odoo.sql_db"), self.assertRaises(psycopg2.IntegrityError), self.env.cr.savepoint():
            Alert.create(vals)

    def test_reopen_refused_when_open_twin(self):
        Alert = self.env["prometeo.ai.alert"].sudo()
        old = Alert.create({"name": "a", "dedup_key": "k", "routine_id": self.routine.id, "state": "resolved"})
        Alert.create({"name": "a", "dedup_key": "k", "routine_id": self.routine.id})
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            old.action_reopen()

    def test_cap_alert_not_recreated_after_resolve(self):
        Alert = self.env["prometeo.ai.alert"].sudo()
        a = Alert._create_system_alert("tope-2026-11", "t", "s", "high", once=True)
        a.state = "resolved"
        Alert._create_system_alert("tope-2026-11", "t", "s", "high", once=True)
        self.assertEqual(Alert.search_count([("dedup_key", "=", "tope-2026-11")]), 1)

    # 5
    def test_tokens_before_failure_are_logged(self):
        read = llm_tool("search_count", {"model": "res.partner", "domain": "[]"}, input_tokens=1_000_000)
        with self.fake_llm(read, llm.LlmError("caído", 500)):
            run = self.routine._run_once()
        self.assertEqual((run.status, run.input_tokens), ("error", 1_000_000))
        self.assertAlmostEqual(run.cost, 1.0, places=3)

    # 6
    def test_malformed_200_is_llm_error(self):
        prov = {"type": "openai", "api_key": "k", "base_url": "https://x"}
        with patch("requests.post", return_value=fake_response(200, [])):
            with self.assertRaises(llm.LlmError):
                llm.chat(prov, "m", "s", USER, [], 10)
        body = {"choices": [{"message": {"tool_calls": [{"id": "c"}]}}]}
        with patch("requests.post", return_value=fake_response(200, body)):
            with self.assertRaises(llm.LlmError):
                llm.chat(prov, "m", "s", USER, [], 10)

    def test_chat_unexpected_error_returns_error(self):
        conv = self.env["prometeo.ai.conversation"].with_user(self.agent_user).create({})
        with self.fake_llm(RuntimeError("boom")), mute_logger("odoo.addons.prometeo_ai_agent.models.prometeo_ai_conversation"):
            r = conv.send_message("hola")
        self.assertEqual(r["status"], "error")

    # 7
    def test_google_tool_ids_unique(self):
        prov = {"type": "google", "api_key": "k", "base_url": "https://x"}
        body = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "a", "args": {}}}]}}]}
        ids = set()
        for _i in range(2):
            with patch("requests.post", return_value=fake_response(200, body)):
                ids.add(llm.chat(prov, "m", "s", USER, [], 10)["tool_calls"][0]["id"])
        self.assertEqual(len(ids), 2)

    # 8
    def test_high_alert_not_notified_when_run_fails(self):
        read = llm_tool("search_read", {"model": "res.partner", "domain": json.dumps([["id", "=", self.partner.id]]),
                                        "fields": ["name"]})
        alert = llm_tool("create_alert", {"key": "k", "title": "t", "summary": "s", "severity": "high",
                                          "model": "res.partner", "record_ids": [self.partner.id]}, call_id="c2")
        Alert = type(self.env["prometeo.ai.alert"])
        with patch.object(Alert, "message_notify") as notify:
            with self.fake_llm(read, alert, llm.LlmError("caído", 500)):
                self.routine._run_once()
            notify.assert_not_called()
            with self.fake_llm(read, alert, llm_text("ok")):
                self.routine._run_once()
            self.assertEqual(notify.call_count, 1)
            # 9
            self.assertIn("IA", notify.call_args.kwargs["subject"])
            self.assertIn("Verificá", notify.call_args.kwargs["body"])
