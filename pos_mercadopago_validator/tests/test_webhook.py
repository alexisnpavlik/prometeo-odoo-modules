import json
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged


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
