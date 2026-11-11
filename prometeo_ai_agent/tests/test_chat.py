import json

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.prometeo_ai_agent import llm
from odoo.addons.prometeo_ai_agent.models.prometeo_ai_conversation import CHAT_LOCK_KEY

from .common import AiAgentCase, llm_text, llm_tool


@tagged("post_install", "-at_install")
class TestChat(AiAgentCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.env["res.company"].create({"name": "AI Chat Otra"})
        cls.hidden = cls.env["res.partner"].create({"name": "AI Chat Oculto", "company_id": cls.other_company.id})

    def setUp(self):
        super().setUp()
        self.Conv = self.env["prometeo.ai.conversation"].with_user(self.agent_user)
        self.conv = self.Conv.create({})
        self.Run = self.env["prometeo.ai.run"].sudo()
        self.Run.search([]).unlink()

    def test_send_message_saves_turn_and_logs_run(self):
        with self.fake_llm(llm_text("hola")):
            r = self.conv.send_message("buen día")
        self.assertEqual(r, {"status": "ok", "reply": "hola"})
        self.assertEqual([m["role"] for m in self.conv.get_messages()], ["user", "assistant"])
        self.assertEqual(self.Run.search_count([("kind", "=", "chat"), ("user_id", "=", self.agent_user.id)]), 1)

    def test_tool_messages_stored_but_hidden(self):
        tool = llm_tool("search_count", {"model": "res.partner", "domain": "[]"})
        with self.fake_llm(tool, llm_text("hay muchos")):
            self.conv.send_message("¿cuántos contactos?")
        self.assertIn("tool", self.conv.message_ids.mapped("role"))
        self.assertEqual([m["role"] for m in self.conv.get_messages()], ["user", "assistant"])

    def test_history_is_sent_on_second_turn(self):
        with self.fake_llm(llm_text("hola")):
            self.conv.send_message("primero")
        with self.fake_llm(llm_text("dale")) as mock:
            self.conv.send_message("segundo")
        sent = mock.call_args.args[3]
        self.assertEqual([(m["role"], m["content"]) for m in sent],
                         [("user", "primero"), ("assistant", "hola"), ("user", "segundo")])

    def test_name_set_from_first_message(self):
        text = "¿Qué traslados quedaron pendientes esta semana en la sucursal centro?"
        with self.fake_llm(llm_text("hola")):
            self.conv.send_message(text)
        self.assertEqual(self.conv.name, text[:60])
        self.assertEqual(len(self.conv.name), 60)

    def test_llm_error_saves_nothing(self):
        with self.fake_llm(llm.LlmError("caído", 500)):
            r = self.conv.send_message("hola")
        self.assertEqual(r["status"], "error")
        self.assertIn("caído", r["message"])
        self.assertFalse(self.conv.message_ids)
        self.assertEqual(self.Run.search([("kind", "=", "chat")]).status, "error")

    def test_cap_blocks_chat(self):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.monthly_cap_usd", 0.5)
        self.Run._log("chat", self.ai_model, {"input_tokens": 1_000_000, "output_tokens": 0}, status="done")
        with self.fake_llm() as mock:
            r = self.conv.send_message("hola")
        self.assertEqual(r["status"], "cap")
        mock.assert_not_called()

    def test_busy_when_all_slots_taken(self):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.chat_max_concurrent", 1)
        with self.registry.cursor() as other_cr:
            other_cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (CHAT_LOCK_KEY, 0))
            self.assertTrue(other_cr.fetchone()[0])
            with self.fake_llm() as mock:
                r = self.conv.send_message("hola")
            other_cr.rollback()
        self.assertEqual(r, {"status": "busy"})
        mock.assert_not_called()
        self.assertFalse(self.conv.message_ids)

    def test_other_user_cannot_read_conversation(self):
        with self.assertRaises(AccessError):
            self.conv.with_user(self.admin_user).read(["name"])
        self.assertFalse(self.env["prometeo.ai.conversation"].with_user(self.admin_user).search(
            [("id", "=", self.conv.id)]))
        with self.fake_llm(llm_text("hola")):
            self.conv.send_message("hola")
        self.assertFalse(self.env["prometeo.ai.message"].with_user(self.admin_user).search(
            [("conversation_id", "=", self.conv.id)]))

    def test_chat_reads_with_chatting_user_permissions(self):
        tool = llm_tool("search_read", {"model": "res.partner", "domain": json.dumps([["id", "=", self.hidden.id]]),
                                        "fields": ["name"]})
        with self.fake_llm(tool, llm_text("no veo nada")) as mock:
            self.conv.send_message("buscá el oculto")
        self.assertEqual(json.loads(mock.call_args.args[3][-1]["content"])["records"], [])

    def test_no_default_model_returns_error(self):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.default_model_id", "")
        with self.fake_llm() as mock:
            r = self.conv.send_message("hola")
        self.assertEqual(r["status"], "error")
        mock.assert_not_called()

    def test_empty_message_raises(self):
        with self.assertRaises(UserError):
            self.conv.send_message("   ")

    def test_available_models(self):
        models = self.Conv.get_available_models()
        self.assertIn({"id": self.ai_model.id, "label": self.ai_model.display_name, "is_default": True}, models)

    def test_chat_has_no_alert_tools(self):
        with self.fake_llm(llm_text("hola")) as mock:
            self.conv.send_message("hola")
        self.assertNotIn("create_alert", [t["name"] for t in mock.call_args.args[4]])


@tagged("post_install", "-at_install")
class TestChatAllCompanies(AiAgentCase):

    def test_chat_reads_all_allowed_companies_not_only_selected(self):
        company_b = self.env["res.company"].create({"name": "AI Empresa B"})
        self.agent_user.write({"company_ids": [(4, company_b.id)]})
        partner_b = self.env["res.partner"].create({"name": "AI Partner B", "company_id": company_b.id})
        conv = self.env["prometeo.ai.conversation"].with_user(self.agent_user).with_context(
            allowed_company_ids=[self.agent_user.company_id.id]).create({})
        tool = llm_tool("search_count", {"model": "res.partner", "domain": json.dumps([["id", "=", partner_b.id]])})
        with self.fake_llm(tool, llm_text("ok")) as mock:
            conv.send_message("buscá")
        self.assertEqual(json.loads(mock.call_args.args[3][-1]["content"])["count"], 1)
        self.assertIn("AI Empresa B", mock.call_args.args[2])
