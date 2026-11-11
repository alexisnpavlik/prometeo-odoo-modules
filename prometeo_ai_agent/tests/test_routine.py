import json
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import new_test_user, tagged

from odoo.addons.prometeo_ai_agent import llm

from .common import AiAgentCase, llm_text, llm_tool


@tagged("post_install", "-at_install")
class TestRoutine(AiAgentCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "AI Routine Partner"})
        cls.other_company = cls.env["res.company"].create({"name": "AI Rutina Otra"})
        cls.hidden = cls.env["res.partner"].create({"name": "AI Rutina Oculto", "company_id": cls.other_company.id})
        cls.admin_user.tz = "America/Argentina/Buenos_Aires"

    def setUp(self):
        super().setUp()
        self.Routine = self.env["prometeo.ai.routine"]
        self.Alert = self.env["prometeo.ai.alert"].sudo()
        self.Run = self.env["prometeo.ai.run"].sudo()
        self.routine = self.make()

    def make(self, **vals):
        base = {"name": "Rutina", "prompt": "Revisá contactos", "run_as_user_id": self.admin_user.id,
                "recipient_ids": [(6, 0, [self.agent_user.id])], "interval_type": "days", "run_hour": 8.0}
        base.update(vals)
        return self.Routine.create(base)

    def read_partner(self, ids):
        return llm_tool("search_read", {"model": "res.partner", "domain": json.dumps([["id", "in", ids]]),
                                        "fields": ["name"]})

    def alert_call(self, key="k", severity="low"):
        return llm_tool("create_alert", {"key": key, "title": "Contacto raro", "summary": "x", "severity": severity,
                                         "model": "res.partner", "record_ids": [self.partner.id]}, call_id="call_2")

    def routine_alerts(self, routine=None):
        return self.Alert.search([("routine_id", "=", (routine or self.routine).id)])

    def test_next_run_daily_uses_user_timezone(self):
        nxt = self.routine._next_run_after(datetime(2026, 11, 10, 15, 0))
        self.assertEqual(nxt, datetime(2026, 11, 11, 11, 0))

    def test_next_run_hourly_and_weekly(self):
        hourly = self.make(interval_type="hours", interval_number=3)
        self.assertEqual(hourly._next_run_after(datetime(2026, 11, 10, 15, 0)), datetime(2026, 11, 10, 18, 0))
        weekly = self.make(interval_type="weeks")
        self.assertEqual(weekly._next_run_after(datetime(2026, 11, 10, 15, 0)), datetime(2026, 11, 17, 11, 0))

    def test_new_daily_routine_next_run_is_next_occurrence(self):
        self.assertGreater(self.routine.next_run, fields.Datetime.now())
        self.assertLessEqual(self.routine.next_run, fields.Datetime.now() + timedelta(days=1))

    def test_run_creates_alert_and_logs_run(self):
        with self.fake_llm(self.read_partner(self.partner.ids), self.alert_call(), llm_text("listo")):
            run = self.routine._run_once()
        self.assertEqual((run.status, run.tool_calls, run.kind, run.routine_id), ("done", 2, "routine", self.routine))
        self.assertEqual(self.Alert.search_count([("routine_id", "=", self.routine.id), ("state", "=", "new")]), 1)
        self.assertEqual(self.routine.last_status, "done")
        self.assertGreater(self.routine.next_run, fields.Datetime.now())

    def test_run_reads_as_run_as_user(self):
        with self.fake_llm(self.read_partner(self.hidden.ids), llm_text("nada")) as mock:
            self.routine._run_once()
        tool_result = json.loads(mock.call_args_list[1].args[3][-1]["content"])
        self.assertEqual(tool_result["records"], [])

    def test_open_alerts_are_sent_to_the_model(self):
        self.Alert.create({"name": "Vieja", "dedup_key": "faltantes-x", "routine_id": self.routine.id})
        with self.fake_llm(llm_text("Sin novedades")) as mock:
            self.routine._run_once()
        self.assertIn("faltantes-x", mock.call_args_list[0].args[3][0]["content"])

    def test_llm_error_counts_failure_and_rolls_back_alerts(self):
        with self.fake_llm(self.read_partner(self.partner.ids), self.alert_call(), llm.LlmError("caído", 500)):
            run = self.routine._run_once()
        self.assertEqual(run.status, "error")
        self.assertIn("caído", run.error)
        self.assertFalse(self.routine_alerts())
        self.assertEqual(self.routine.failure_count, 1)

    def test_three_failures_pause_and_alert_admins(self):
        for _i in range(3):
            with self.fake_llm(llm.LlmError("caído", 500)):
                self.routine._run_once()
        self.assertTrue(self.routine.paused)
        system = self.Alert.search([("kind", "=", "system"), ("dedup_key", "=", "pausada-%s" % self.routine.id)])
        self.assertEqual(len(system), 1)
        self.assertEqual(system.severity, "high")
        self.routine.action_resume()
        self.assertEqual((self.routine.paused, self.routine.failure_count), (False, 0))

    def test_incomplete_keeps_alerts_and_is_not_failure(self):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.routine_max_tool_calls", 2)
        with self.fake_llm(self.read_partner(self.partner.ids), self.alert_call(), llm_text("parcial")):
            run = self.routine._run_once()
        self.assertEqual(run.status, "incomplete")
        self.assertEqual(len(self.routine_alerts()), 1)
        self.assertEqual((self.routine.failure_count, self.routine.incomplete_count), (0, 1))

    def test_three_incompletes_alert_but_do_not_pause(self):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.routine_max_tool_calls", 1)
        for _i in range(3):
            with self.fake_llm(self.read_partner(self.partner.ids), llm_text("parcial")):
                self.routine._run_once()
        self.assertFalse(self.routine.paused)
        self.assertEqual(self.Alert.search_count([("dedup_key", "=", "incompleta-%s" % self.routine.id)]), 1)

    def test_cap_skips_run(self):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.monthly_cap_usd", 0.5)
        self.Run._log("chat", self.ai_model, {"input_tokens": 1_000_000, "output_tokens": 0}, status="done")
        with self.fake_llm() as mock:
            run1 = self.routine._run_once()
            self.routine._run_once()
        mock.assert_not_called()
        self.assertEqual(run1.status, "skipped_cap")
        self.assertEqual(self.Alert.search_count([("kind", "=", "system"), ("dedup_key", "=like", "tope-%")]), 1)

    def test_misconfigured_routine_errors_and_dispatcher_continues(self):
        archived = new_test_user(self.env, login="ai_archived_test", groups="base.group_user")
        archived.active = False
        bad = self.make(name="Mala", run_as_user_id=archived.id)
        past = fields.Datetime.now() - timedelta(minutes=1)
        (bad | self.routine).write({"next_run": past})
        with self.fake_llm(llm_text("Sin novedades")):
            self.Routine._cron_dispatch()
        self.assertEqual(bad.last_status, "error")
        self.assertEqual(self.routine.last_status, "done")

    def test_no_recipients_is_error(self):
        self.routine.recipient_ids = [(5,)]
        with self.fake_llm() as mock:
            run = self.routine._run_once()
        self.assertEqual(run.status, "error")
        mock.assert_not_called()

    def test_no_model_is_error(self):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.default_model_id", "")
        with self.fake_llm() as mock:
            run = self.routine._run_once()
        self.assertEqual(run.status, "error")
        mock.assert_not_called()

    def test_dispatch_skips_paused_inactive_and_not_due(self):
        past = fields.Datetime.now() - timedelta(minutes=1)
        paused = self.make(name="Pausada", paused=True, next_run=past)
        inactive = self.make(name="Inactiva", active=False, next_run=past)
        self.routine.next_run = fields.Datetime.now() + timedelta(hours=1)
        with self.fake_llm() as mock:
            self.Routine._cron_dispatch()
        mock.assert_not_called()
        self.assertFalse(paused.last_run or inactive.last_run or self.routine.last_run)

    def test_template_availability_follows_installed_modules(self):
        Template = self.env["prometeo.ai.routine.template"]
        base_tpl = Template.create({"name": "T base", "prompt": "x", "required_module": "base"})
        missing = Template.create({"name": "T falta", "prompt": "x", "required_module": "modulo_inexistente"})
        available = Template.search([("is_available", "=", True)])
        self.assertIn(base_tpl, available)
        self.assertNotIn(missing, available)

    def test_template_use_creates_routine_for_current_user(self):
        tpl = self.env["prometeo.ai.routine.template"].create({"name": "T", "prompt": "Revisá", "required_module": "base"})
        action = tpl.with_user(self.admin_user).action_use()
        routine = self.Routine.browse(action["res_id"])
        self.assertEqual((routine.prompt, routine.run_as_user_id, routine.recipient_ids, routine.template_id),
                         ("Revisá", self.admin_user, self.admin_user, tpl))
        self.assertTrue(routine.active)

    def test_user_sees_public_or_own_group_or_recipient_routines_only(self):
        group = self.env["res.groups"].create({"name": "AI grupo test"})
        public = self.make(name="Pública", recipient_ids=[(5,)])
        private = self.make(name="Privada", is_public=False, recipient_ids=[(5,)])
        by_group = self.make(name="Del grupo", is_public=False, group_ids=[(6, 0, group.ids)], recipient_ids=[(5,)])
        mine = self.make(name="Me llega", is_public=False)
        visible = self.Routine.with_user(self.agent_user).search([("id", "in", (public | private | by_group | mine).ids)])
        self.assertEqual(visible, public | mine)
        self.agent_user.groups_id = [(4, group.id)]
        visible = self.Routine.with_user(self.agent_user).search([("id", "in", (public | private | by_group | mine).ids)])
        self.assertEqual(visible, public | by_group | mine)


@tagged("post_install", "-at_install")
class TestRoutineDefaultCompanies(AiAgentCase):

    def test_new_routine_and_template_use_all_user_companies(self):
        company_b = self.env["res.company"].create({"name": "AI Rutina Empresa B"})
        self.admin_user.write({"company_ids": [(4, company_b.id)]})
        expected = self.admin_user.company_ids
        Routine = self.env["prometeo.ai.routine"].with_user(self.admin_user)
        self.assertEqual(Routine.create({"name": "x"}).company_ids, expected)
        tpl = self.env["prometeo.ai.routine.template"].create({"name": "T", "prompt": "x", "required_module": "base"})
        action = tpl.with_user(self.admin_user).action_use()
        self.assertEqual(Routine.browse(action["res_id"]).company_ids, expected)


@tagged("post_install", "-at_install")
class TestTemplateRunInChat(AiAgentCase):

    def test_run_now_opens_chat_with_prompt(self):
        tpl = self.env["prometeo.ai.routine.template"].create({"name": "T", "prompt": "Revisá X", "required_module": "base"})
        action = tpl.with_user(self.admin_user).action_run_in_chat()
        self.assertEqual(action["tag"], "prometeo_ai_agent.chat")
        self.assertEqual(action["params"]["prompt"], "Revisá X")
        self.assertFalse(self.env["prometeo.ai.routine"].search_count([("template_id", "=", tpl.id)]))
