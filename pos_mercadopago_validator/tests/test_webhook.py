import json
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged

from ..services.mp_client import MercadoPagoClient
from .test_normalization import QR_EXTERNAL


@tagged("post_install", "-at_install")
class TestWebhook(HttpCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
            "access_token": "APP_USR-fake", "last_validated_at": "2026-08-03 12:00:00",
        })
        self.account.write({"active": True})

    def _post(self, payload):
        return self.url_open(
            "/pos_mercadopago_validator/notification",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )

    def test_malformed_payload_still_returns_200(self):
        """Un payload sin data.id no rompe: se responde 200 y se ignora."""
        response = self._post({"hola": "mundo"})
        self.assertEqual(response.status_code, 200)

    def test_only_the_id_is_read_from_the_body(self):
        """El cuerpo del webhook no es fuente de verdad: se reconsulta la API."""
        with patch.object(
            type(self.env["mercadopago.account"]), "ingest_payment_id", return_value=True
        ) as mocked:
            self._post({
                "type": "payment", "data": {"id": "170951482351"},
                "transaction_amount": 999999, "status": "approved",
            })
        self.assertTrue(mocked.called)
        self.assertEqual(mocked.call_args[0][0], "170951482351")

    def test_owner_ingests_even_if_not_first_in_the_loop(self):
        """Si la primera cuenta activa no es la dueña, se sigue probando hasta encontrarla."""
        # unlink(), no desactivar: mp_user_id es único por compañía y "owner"
        # necesita el mismo Collector ID que self.account para este escenario.
        self.account.unlink()
        decoy = self.env["mercadopago.account"].create({
            "name": "Decoy", "mode": "production", "mp_user_id": "111111111",
            "access_token": "APP_USR-decoy", "last_validated_at": "2026-08-03 12:00:00",
        })
        decoy.write({"active": True})
        owner = self.env["mercadopago.account"].create({
            "name": "Dueña real", "mode": "production", "mp_user_id": "430185252",
            "access_token": "APP_USR-owner", "last_validated_at": "2026-08-03 12:00:00",
        })
        owner.write({"active": True})
        self.assertLess(decoy.id, owner.id, "el test requiere que la dueña no sea la primera")

        with patch.object(MercadoPagoClient, "get_payment", return_value=QR_EXTERNAL):
            response = self._post({"type": "payment", "data": {"id": "170951482351"}})

        self.assertEqual(response.status_code, 200)
        payment = self.env["mercadopago.payment"].search([
            ("mp_payment_id", "=", "170951482351"),
        ])
        self.assertEqual(payment.account_id, owner)

    def test_second_account_is_not_queried_once_payment_already_ingested(self):
        """Un pago ya ingerido (reintento de MP, o el cron llegó primero) no debe
        hacer que el webhook le pegue a la API con las credenciales de otra cuenta."""
        self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351",
            "account_id": self.account.id,
            "amount": 1500,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": "2026-08-03 11:21:49",
            "source": "qr",
            "state": "available",
        })
        other_account = self.env["mercadopago.account"].create({
            "name": "Otra cuenta", "mode": "production", "mp_user_id": "999999999",
            "access_token": "APP_USR-otra", "last_validated_at": "2026-08-03 12:00:00",
        })
        other_account.write({"active": True})

        with patch.object(MercadoPagoClient, "get_payment", return_value=QR_EXTERNAL) as mocked:
            response = self._post({"type": "payment", "data": {"id": "170951482351"}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mocked.call_count, 1,
            "el pago ya ingerido no debe llevar a consultar la segunda cuenta",
        )
