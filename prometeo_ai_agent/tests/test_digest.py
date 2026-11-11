from datetime import datetime, timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo.tests import new_test_user, tagged

from .common import AiAgentCase

NOW = datetime(2026, 11, 11, 11, 30)  # 08:30 en Buenos Aires


@tagged("post_install", "-at_install")
class TestDigest(AiAgentCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_user = new_test_user(cls.env, login="ai_digest_other", groups="base.group_user,prometeo_ai_agent.group_user")
        cls.env.company.partner_id.tz = "America/Argentina/Buenos_Aires"
        cls.Alert = cls.env["prometeo.ai.alert"].sudo()

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.digest_hour", 8)
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.digest_last_date", "")
        self.Alert.search([]).unlink()

    def alert(self, severity, hours_ago, user=None, key=None):
        when = NOW - timedelta(hours=hours_ago)
        return self.Alert.create({"name": "A %s %s" % (severity, hours_ago), "severity": severity, "kind": "system",
                                  "dedup_key": key or "%s-%s" % (severity, hours_ago), "first_seen": when,
                                  "last_seen": when, "recipient_ids": [(6, 0, (user or self.agent_user).ids)]})

    def test_digest_groups_by_severity_last_24h(self):
        self.alert("high", 2)
        self.alert("low", 3)
        self.alert("medium", 30)
        with freeze_time(NOW):
            d = self.Alert._digest_for(self.agent_user)
        self.assertEqual((len(d["high"]), len(d["medium"]), len(d["low"])), (1, 0, 1))
        self.assertEqual(d["open_total"], 3)

    def test_no_recent_alerts_no_digest(self):
        self.alert("medium", 30)
        with freeze_time(NOW), patch.object(type(self.Alert), "message_notify") as notify:
            self.assertIsNone(self.Alert._digest_for(self.agent_user))
            self.Alert._cron_send_daily_digest()
        notify.assert_not_called()

    def test_digest_sent_once_per_day(self):
        self.alert("high", 2)
        self.alert("low", 1, user=self.other_user)
        with freeze_time(NOW), patch.object(type(self.Alert), "message_notify") as notify:
            self.Alert._cron_send_daily_digest()
            self.Alert._cron_send_daily_digest()
        self.assertEqual(notify.call_count, 2)
        partners = sorted(c.kwargs["partner_ids"][0] for c in notify.call_args_list)
        self.assertEqual(partners, sorted([self.agent_user.partner_id.id, self.other_user.partner_id.id]))

    def test_digest_not_sent_outside_hour(self):
        self.alert("high", 2)
        with freeze_time(NOW + timedelta(hours=2)), patch.object(type(self.Alert), "message_notify") as notify:
            self.Alert._cron_send_daily_digest()
        notify.assert_not_called()

    def test_digest_only_includes_own_alerts(self):
        mine = self.alert("high", 2)
        self.alert("high", 2, user=self.other_user, key="other")
        with freeze_time(NOW):
            d = self.Alert._digest_for(self.agent_user)
        self.assertEqual(d["high"], mine)

    def test_digest_body_lists_titles(self):
        self.alert("high", 2)
        with freeze_time(NOW), patch.object(type(self.Alert), "message_notify") as notify:
            self.Alert._cron_send_daily_digest()
        body = str(notify.call_args.kwargs["body"])
        self.assertIn("A high 2", body)
        self.assertIn("1 alertas abiertas", body)
