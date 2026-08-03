from unittest.mock import patch

import psycopg2

from odoo.tests.common import TransactionCase, tagged

from .test_normalization import QR_EXTERNAL


@tagged("post_install", "-at_install")
class TestIngestRaceCondition(TransactionCase):
    """Cubre la concurrencia entre webhook y cron sobre ingest_raw().

    Antes de esta task, ingest_raw() sólo lo llamaba el cron de forma
    secuencial. Con el webhook, dos llamadores pueden hacer el search de
    existencia al mismo tiempo, no encontrar nada, y pisarse en el create().
    """

    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        self.Inbox = self.env["mercadopago.payment"]

    def test_concurrent_create_degrades_gracefully(self):
        """La llamada que pierde la carrera del search no propaga IntegrityError."""
        self.Inbox.create({
            "mp_payment_id": "170951482351",
            "account_id": self.account.id,
            "amount": 1500,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": "2026-08-03 11:21:49",
            "source": "qr",
            "state": "available",
        })

        # Simula la carrera: el search de "¿existe ya?" no encuentra nada,
        # como si corriera antes de que la otra llamada hubiera hecho commit.
        with patch.object(type(self.Inbox), "search", return_value=self.Inbox.browse()):
            try:
                self.Inbox.ingest_raw(self.account, [QR_EXTERNAL])
            except psycopg2.IntegrityError:
                self.fail(
                    "ingest_raw no debe propagar IntegrityError cuando pierde "
                    "la carrera del create()"
                )

        self.assertEqual(
            self.Inbox.search_count([("mp_payment_id", "=", "170951482351")]), 1
        )
