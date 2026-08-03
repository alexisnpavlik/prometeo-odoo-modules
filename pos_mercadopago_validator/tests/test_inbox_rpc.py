from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInboxRpc(TransactionCase):
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
        self.Inbox = self.env["mercadopago.payment"]

    def _payment(self, mp_id, amount, pos_id="64365871", source="qr"):
        return self.Inbox.create({
            "mp_payment_id": mp_id, "account_id": self.account.id, "amount": amount,
            "date_approved": fields_now(), "source": source, "mp_pos_id": pos_id,
            "state": "available",
        })

    def test_only_this_cash_register_qr_is_listed(self):
        """Un pago del QR de otra caja no aparece en esta bandeja."""
        self._payment("111", 1500.0, pos_id="64365871")
        self._payment("222", 1500.0, pos_id="99999999")
        result = self.method.get_mp_inbox(1500.0)
        self.assertEqual([p["mp_payment_id"] for p in result["matching"]], ["111"])

    def test_non_matching_amounts_are_counted_not_listed(self):
        """Los montos distintos no se listan pero se cuentan."""
        self._payment("111", 1500.0)
        self._payment("333", 980.0)
        result = self.method.get_mp_inbox(1500.0)
        self.assertEqual(len(result["matching"]), 1)
        self.assertEqual(result["others_count"], 1)

    def test_alias_excluded_unless_enabled(self):
        """El canal alias sólo entra si el método lo habilita."""
        self._payment("444", 1500.0, pos_id=False, source="alias")
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 0)
        self.method.accept_alias_payments = True
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 1)

    def test_stale_flag_when_never_synced(self):
        """Sin sincronización exitosa, la bandeja se reporta desactualizada."""
        self.assertTrue(self.method.get_mp_inbox(1500.0)["stale"])


def fields_now():
    from odoo import fields
    return fields.Datetime.now()
