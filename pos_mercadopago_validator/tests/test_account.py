from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..services.mp_client import MercadoPagoClient, MercadoPagoError
from .test_normalization import QR_EXTERNAL


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


@tagged("post_install", "-at_install")
class TestIngestPaymentId(TransactionCase):
    """Cubre los tres desenlaces de ingest_payment_id(), camino del webhook."""

    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
            "access_token": "APP_USR-fake", "last_validated_at": "2026-08-03 12:00:00",
        })

    def test_returns_created_for_a_new_ingestable_payment(self):
        """Un pago nuevo e ingestable produce "created"."""
        with patch.object(MercadoPagoClient, "get_payment", return_value=QR_EXTERNAL):
            outcome = self.account.ingest_payment_id("170951482351")
        self.assertEqual(outcome, "created")

    def test_returns_existing_when_already_in_the_inbox(self):
        """Un pago que ya estaba en la bandeja produce "existing", no "created"."""
        self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351",
            "account_id": self.account.id,
            "amount": 1500,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": "2026-08-03 11:21:49",
            "source": "qr",
            "state": "available",
        })
        with patch.object(MercadoPagoClient, "get_payment", return_value=QR_EXTERNAL):
            outcome = self.account.ingest_payment_id("170951482351")
        self.assertEqual(outcome, "existing")

    def test_returns_failed_when_the_api_cannot_resolve_it(self):
        """Si la API no puede resolver el pago, el desenlace es "failed"."""
        with patch.object(MercadoPagoClient, "get_payment", side_effect=MercadoPagoError("404")):
            outcome = self.account.ingest_payment_id("no-existe")
        self.assertEqual(outcome, "failed")
