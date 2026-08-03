from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBusNotification(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        self.config = self.env["pos.config"].create({"name": "Caja A"})
        self.config.write({"payment_method_ids": [(4, self.method.id)]})
        self.config.open_ui()

    def test_notifies_only_configs_with_that_qr(self):
        """El bus es por pos.config: sólo se notifica a la caja dueña del QR."""
        other_config = self.env["pos.config"].create({"name": "Caja B"})
        payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351", "account_id": self.account.id,
            "amount": 1500.0, "date_approved": "2026-08-03 15:21:49",
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })
        notified = []
        original = type(self.env["pos.config"])._notify

        def spy(self_config, *args, **kwargs):
            notified.append(self_config.id)
            return original(self_config, *args, **kwargs)

        with patch.object(type(self.env["pos.config"]), "_notify", spy):
            payment._notify_open_sessions()

        self.assertIn(self.config.id, notified)
        self.assertNotIn(other_config.id, notified)
