from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPaymentMethodConfig(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
            "access_token": "APP_USR-secreto",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "Mercado Pago QR",
            "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id,
            "mp_pos_id": "64365871",
        })

    def test_terminal_option_is_registered(self):
        """La opción aparece en el selector de terminal de pago."""
        selection = self.method._get_payment_terminal_selection()
        self.assertIn("mercadopago_validator", dict(selection))

    def test_defaults_match_spec(self):
        """Los defaults son los acordados: sin auto-imputación, ventana de 5 minutos."""
        self.assertFalse(self.method.auto_impute_single_match)
        self.assertFalse(self.method.accept_alias_payments)
        self.assertEqual(self.method.search_window_minutes, 5)
        self.assertEqual(self.method.amount_tolerance, 0.0)
        self.assertFalse(self.method.require_manager_for_manual)

    def test_no_credential_is_synced_to_the_browser(self):
        """RNF-002: ningún campo de credenciales entra en la carga del POS."""
        fields_sent = self.env["pos.payment.method"]._load_pos_data_fields(False)
        for forbidden in ("access_token", "webhook_secret", "mp_account_id"):
            self.assertNotIn(forbidden, fields_sent)
