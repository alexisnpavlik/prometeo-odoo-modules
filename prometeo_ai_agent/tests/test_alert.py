import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.prometeo_ai_agent.agent import tools

from .common import AiAgentCase


@tagged("post_install", "-at_install")
class TestAlert(AiAgentCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_user = new_test_user(cls.env, login="ai_other_test",
                                       groups="base.group_user,prometeo_ai_agent.group_user")
        cls.routine = cls.env["prometeo.ai.routine"].create({
            "name": "Rutina test", "recipient_ids": [(6, 0, [cls.agent_user.id])]})
        cls.partner = cls.env["res.partner"].create({"name": "AI Alert Partner"})

    def setUp(self):
        super().setUp()
        self.Alert = self.env["prometeo.ai.alert"]
        self.uenv = self.env(user=self.admin_user)
        self.ctx = tools.new_context(routine=self.routine)
        self.h = tools.alert_tool_handlers()

    def create(self, **overrides):
        args = {"key": "k", "title": "Título", "summary": "Resumen", "severity": "low",
                "model": "res.partner", "record_ids": [self.partner.id]}
        args.update(overrides)
        return json.loads(self.h["create_alert"](self.uenv, self.ctx, args))

    def see(self):
        self.ctx["seen"]["res.partner"] = {self.partner.id}

    def alerts(self, **extra):
        domain = [("routine_id", "=", self.routine.id)] + [(k, "=", v) for k, v in extra.items()]
        return self.Alert.sudo().search(domain)

    def test_create_requires_seen_records(self):
        self.assertIn("error", self.create())
        self.see()
        out = self.create()
        self.assertEqual(out["result"], "created")
        alert = self.alerts()
        self.assertEqual((alert.name, alert.state, alert.res_model, alert.res_ids), ("Título", "new", "res.partner", [self.partner.id]))
        self.assertEqual(alert.recipient_ids, self.agent_user)

    def test_create_requires_backing(self):
        self.assertIn("error", self.create(model=None, record_ids=None))
        self.see()
        self.assertIn("error", self.create(severity="urgente"))

    def test_create_with_executed_domain(self):
        domain = [["id", "=", self.partner.id]]
        self.assertIn("error", self.create(record_ids=None, domain=json.dumps(domain)))
        self.ctx["domains"]["res.partner"] = {json.dumps(domain, sort_keys=True)}
        self.assertEqual(self.create(record_ids=None, domain=json.dumps(domain))["result"], "created")
        self.assertEqual(json.loads(self.alerts().res_domain), domain)

    def test_same_key_twice_in_one_run_is_one_alert(self):
        self.see()
        self.create()
        out = self.create(title="Nuevo título")
        self.assertEqual(out["result"], "updated")
        self.assertEqual(len(self.alerts()), 1)
        self.assertEqual(self.alerts().name, "Nuevo título")

    def test_dismissed_key_is_silenced(self):
        self.see()
        self.create()
        self.alerts().with_user(self.agent_user).action_dismiss()
        self.assertEqual(self.create()["result"], "silenced")
        self.assertEqual(len(self.alerts()), 1)
        self.assertGreater(self.alerts().silenced_until, fields.Datetime.now() + timedelta(days=29))

    def test_silence_expires(self):
        self.see()
        self.create()
        alert = self.alerts()
        alert.with_user(self.agent_user).action_dismiss()
        alert.sudo().silenced_until = fields.Datetime.now() - timedelta(minutes=1)
        self.assertEqual(self.create()["result"], "created")
        self.assertEqual(len(self.alerts()), 2)

    def test_resolved_key_can_reappear(self):
        self.see()
        self.create()
        self.alerts().with_user(self.agent_user).action_resolve()
        self.assertEqual(self.create()["result"], "created")
        self.assertEqual(len(self.alerts(state="new")), 1)

    def test_resolve_alert_only_own_routine(self):
        self.see()
        alert_id = self.create()["alert_id"]
        other = self.env["prometeo.ai.routine"].create({"name": "Otra"})
        other_ctx = tools.new_context(routine=other)
        out = json.loads(self.h["resolve_alert"](self.uenv, other_ctx, {"alert_id": alert_id, "reason": "x"}))
        self.assertIn("error", out)
        out = json.loads(self.h["resolve_alert"](self.uenv, self.ctx, {"alert_id": alert_id, "reason": "ya no falta"}))
        self.assertEqual(out["result"], "resolved")
        self.assertEqual((self.alerts().state, self.alerts().resolved_note), ("resolved", "ya no falta"))

    def test_high_severity_notifies(self):
        self.see()
        with patch.object(type(self.Alert), "message_notify") as notify:
            self.create(severity="low")
            self.assertEqual(notify.call_count, 0)
            self.create(key="k2", severity="high")
            self.assertEqual(notify.call_count, 1)
            self.assertEqual(notify.call_args.kwargs["partner_ids"], self.agent_user.partner_id.ids)

    def test_escalation_to_high_notifies_once(self):
        self.see()
        with patch.object(type(self.Alert), "message_notify") as notify:
            self.create(severity="low")
            self.create(severity="high")
            self.create(severity="high")
            self.assertEqual(notify.call_count, 1)

    def test_user_sees_only_own_alerts(self):
        self.see()
        self.create()
        self.assertEqual(self.Alert.with_user(self.agent_user).search_count([("routine_id", "=", self.routine.id)]), 1)
        self.assertEqual(self.Alert.with_user(self.other_user).search_count([("routine_id", "=", self.routine.id)]), 0)
        self.assertEqual(self.Alert.with_user(self.admin_user).search_count([("routine_id", "=", self.routine.id)]), 1)

    def test_systray_count_drops_after_seen(self):
        self.see()
        self.create()
        Alert = self.Alert.with_user(self.agent_user)
        before = Alert.systray_count()
        self.alerts().with_user(self.agent_user).action_mark_seen()
        self.assertEqual(Alert.systray_count(), before - 1)

    def test_non_recipient_cannot_dismiss(self):
        self.see()
        self.create()
        with self.assertRaises(AccessError):
            self.alerts().with_user(self.other_user).action_dismiss()

    def test_view_records_uses_ids_or_domain(self):
        self.see()
        self.create()
        action = self.alerts().with_user(self.agent_user).action_view_records()
        self.assertEqual((action["res_model"], action["domain"]), ("res.partner", [("id", "in", [self.partner.id])]))
        alert = self.Alert.sudo().create({"name": "sin registros", "kind": "system", "dedup_key": "s"})
        with self.assertRaises(UserError):
            alert.action_view_records()

    def test_system_alert_goes_to_admins_and_dedups(self):
        a1 = self.Alert._create_system_alert("tope-x", "Tope", "Se alcanzó")
        a2 = self.Alert._create_system_alert("tope-x", "Tope", "Se alcanzó")
        self.assertEqual(a1, a2)
        self.assertIn(self.admin_user, a1.recipient_ids)
        self.assertNotIn(self.agent_user, a1.recipient_ids)
