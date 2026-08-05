from odoo.tests.common import TransactionCase, tagged

from .test_normalization import ALIAS, OUTGOING, QR_EXTERNAL, QR_INTERNAL


@tagged("post_install", "-at_install")
class TestIngestor(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        self.Inbox = self.env["mercadopago.payment"]

    def test_ingest_creates_only_ingestable_payments(self):
        """Los pagos salientes se descartan en la ingesta."""
        self.Inbox.ingest_raw(self.account, [QR_EXTERNAL, ALIAS, OUTGOING])
        self.assertEqual(self.Inbox.search_count([("account_id", "=", self.account.id)]), 2)

    def test_ingest_is_idempotent(self):
        """La misma notificación entregada tres veces produce un solo registro."""
        for _ in range(3):
            self.Inbox.ingest_raw(self.account, [QR_EXTERNAL])
        self.assertEqual(
            self.Inbox.search_count([("mp_payment_id", "=", "170951482351")]), 1
        )

    def test_ingest_resolves_partner_by_vat(self):
        """El CUIT del canal INTRA_PSP resuelve el cliente contra res.partner."""
        partner = self.env["res.partner"].create({
            "name": "Cliente Conocido", "vat": "27964493338",
        })
        self.Inbox.ingest_raw(self.account, [QR_INTERNAL])
        payment = self.Inbox.search([("mp_payment_id", "=", "171858334766")])
        self.assertEqual(payment.partner_id, partner)
        self.assertEqual(payment.display_payer, "Cliente Conocido")

    def test_ingest_does_not_reopen_matched_payment(self):
        """Un pago ya imputado no vuelve a available por una reingesta."""
        self.Inbox.ingest_raw(self.account, [QR_EXTERNAL])
        payment = self.Inbox.search([("mp_payment_id", "=", "170951482351")])
        payment.write({"state": "matched"})
        self.Inbox.ingest_raw(self.account, [QR_EXTERNAL])
        self.assertEqual(payment.state, "matched")
