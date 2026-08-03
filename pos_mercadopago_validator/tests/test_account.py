from unittest.mock import patch

from odoo import fields
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
class TestFrecuenciaDelCron(TransactionCase):
    """F-3 e I-3: quién decide cada cuánto se consulta, y cuándo corre el cron."""

    def setUp(self):
        super().setUp()
        self.company = self.env["res.company"].search([], limit=1)
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=self.company.ids))
        self.account = self.env["mercadopago.account"].with_company(self.company).create({
            "name": "Cuenta cron", "mode": "production", "mp_user_id": "430185252",
            "access_token": "APP_USR-fake", "last_validated_at": "2026-08-03 12:00:00",
            "company_id": self.company.id,
        })
        journal = self.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", self.company.id),
        ], limit=1)
        self.method = self.env["pos.payment.method"].with_company(self.company).create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
            "company_id": self.company.id,
        })

    def test_the_interval_comes_from_the_payment_methods(self):
        """Spec §6.3: la frecuencia es la configurada, y manda la más exigente."""
        self.method.poll_interval_seconds = 120
        self.env["pos.payment.method"].with_company(self.company).create({
            "name": "MP QR caja B", "journal_id": self.method.journal_id.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "99999999",
            "company_id": self.company.id, "poll_interval_seconds": 45,
        })
        self.assertEqual(self.account._poll_interval_seconds(), 45)

    def test_an_account_never_synced_is_always_due(self):
        """Sin `last_sync_at` no hay nada que esperar."""
        self.assertFalse(self.account.last_sync_at)
        self.assertTrue(self.account._is_due_for_polling())

    def test_an_account_synced_within_its_interval_is_skipped(self):
        """El cron es el reloj; el intervalo lo aplica la cuenta."""
        self.method.poll_interval_seconds = 600
        self.account.sudo().last_sync_at = fields.Datetime.now()
        self.assertFalse(self.account._is_due_for_polling())

        self.account.sudo().last_sync_at = fields.Datetime.subtract(
            fields.Datetime.now(), seconds=601
        )
        self.assertTrue(self.account._is_due_for_polling())

    def _accounts_polled_by_the_cron(self):
        """Corre el cron espiando qué cuentas terminan consultando la API.

        Se mira la lista de ids y no `called`: la base puede tener otras
        cuentas activas y lo que importa es si **ésta** entró en la corrida.
        """
        polled = []

        def spy(records):
            polled.extend(records.ids)

        with patch.object(type(self.account), "ingest_now", spy):
            self.env["mercadopago.account"].cron_ingest_payments()
        return polled

    def _open_a_register(self, name):
        """Abre una caja con el método de este módulo, para que el cron trabaje."""
        config = self.env["pos.config"].with_company(self.company).create({
            "name": name, "company_id": self.company.id,
        })
        config.write({"payment_method_ids": [(6, 0, [self.method.id])]})
        config.open_ui()
        return config

    def test_the_cron_honours_the_interval(self):
        """Una cuenta que no está vencida no se consulta en esta corrida."""
        self.method.poll_interval_seconds = 600
        self.account.sudo().write({"active": True, "last_sync_at": fields.Datetime.now()})
        self._open_a_register("Caja cron")

        self.assertNotIn(
            self.account.id, self._accounts_polled_by_the_cron(),
            "Se consultó una cuenta que no había cumplido su intervalo",
        )

        self.account.sudo().last_sync_at = fields.Datetime.subtract(
            fields.Datetime.now(), seconds=601
        )
        self.assertIn(
            self.account.id, self._accounts_polled_by_the_cron(),
            "La cuenta vencida no se consultó",
        )

    def test_the_cron_runs_with_a_session_still_in_opening_control(self):
        """I-3: el predicado de sesión abierta es el mismo que el del bus.

        `state` pasa por "opening_control" hasta que el cajero confirma el
        conteo de apertura. Con `state == "opened"` el bus notificaba pero el
        ingestor no corría: la caja abierta miraba una bandeja que nadie
        llenaba.
        """
        self.account.sudo().write({"active": True})
        config = self._open_a_register("Caja en apertura")
        # Todas las sesiones abiertas de la base pasan a "opening_control": con
        # el predicado viejo (state == "opened") no habría ninguna y el cron
        # tenía que quedarse quieto; con el correcto, trabaja.
        self.env["pos.session"].search([("state", "!=", "closed")]).write(
            {"state": "opening_control"}
        )
        self.assertEqual(config.current_session_id.state, "opening_control")
        self.assertFalse(self.env["pos.session"].search_count([("state", "=", "opened")]))

        self.assertIn(
            self.account.id, self._accounts_polled_by_the_cron(),
            "El ingestor no corrió con la caja abierta sin confirmar el conteo",
        )


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
