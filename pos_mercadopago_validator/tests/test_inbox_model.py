import psycopg2

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestInboxModel(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta",
            "mode": "production",
            "mp_user_id": "430185252",
        })

    def _payment(self, mp_id, amount=1500.0):
        return self.env["mercadopago.payment"].create({
            "mp_payment_id": mp_id,
            "account_id": self.account.id,
            "amount": amount,
            "date_approved": "2026-08-03 15:21:49",
            "source": "qr",
            "state": "available",
        })

    def test_mp_payment_id_is_unique(self):
        """Dos ingestas del mismo pago no pueden coexistir."""
        self._payment("170951482351")
        with self.assertRaises(psycopg2.IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self._payment("170951482351")

    def test_one_payment_per_pos_payment_line(self):
        """Un mismo pos.payment no puede recibir dos pagos de Mercado Pago."""
        first = self._payment("111")
        second = self._payment("222")
        first.write({"pos_payment_id": 1, "state": "matched"})
        with self.assertRaises(psycopg2.IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                second.write({"pos_payment_id": 1, "state": "matched"})

    def test_null_pos_payment_id_does_not_collide(self):
        """La restricción es parcial: varios pagos sin imputar conviven."""
        self._payment("333")
        self._payment("444")
        self.assertEqual(
            self.env["mercadopago.payment"].search_count([("state", "=", "available")]), 2
        )
