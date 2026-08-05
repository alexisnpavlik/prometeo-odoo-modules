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
        """La llamada que pierde la carrera del search no propaga IntegrityError,
        y termina con el mismo resultado que la ganadora: releyó su registro y
        lo actualizó, en vez de comportarse como si no hubiera pasado nada."""
        winner = self.Inbox.create({
            "mp_payment_id": "170951482351",
            "account_id": self.account.id,
            # Monto "viejo" a propósito: si el except sólo loguea y sigue sin
            # releer, este valor quedaría sin actualizar y el test lo detecta.
            "amount": 1.0,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": "2026-08-03 11:21:49",
            "source": "qr",
            "state": "available",
        })

        # Simula la carrera: sólo el primer search() (el chequeo de "¿existe
        # ya?") devuelve vacío, como si corriera antes de que la otra llamada
        # hubiera hecho commit. Las búsquedas siguientes -incluida la que el
        # propio fix hace para releer al ganador tras el IntegrityError- deben
        # comportarse con normalidad, o el test no distinguiría "releyó y
        # actualizó" de "el mock también le tapó los ojos al fix".
        original_search = type(self.Inbox).search
        calls = []

        def fake_search(inbox_self, *args, **kwargs):
            if not calls:
                calls.append(1)
                return inbox_self.browse()
            return original_search(inbox_self, *args, **kwargs)

        with patch.object(type(self.Inbox), "search", fake_search):
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
        winner.invalidate_recordset()
        self.assertEqual(
            winner.amount, 1500,
            "la llamada perdedora debe releer el registro ganador y actualizarlo "
            "con sus propios valores, no ignorar la carrera en silencio",
        )
