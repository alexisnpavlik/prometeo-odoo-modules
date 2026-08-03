from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMercadoPagoAccount(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta de prueba",
            "access_token": "APP_USR-fake",
            "mode": "sandbox",
        })

    def test_account_starts_inactive_until_validated(self):
        """Una cuenta nueva no puede activarse sin haber validado credenciales."""
        self.assertFalse(self.account.last_validated_at)
        with self.assertRaises(UserError):
            self.account.write({"active": True})

    def test_activation_allowed_after_validation(self):
        """Con last_validated_at cargado, la activación procede."""
        self.account.write({
            "last_validated_at": "2026-08-03 12:00:00",
            "mp_user_id": "430185252",
        })
        self.account.write({"active": True})
        self.assertTrue(self.account.active)
