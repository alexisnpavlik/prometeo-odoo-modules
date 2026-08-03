from odoo.tests.common import TransactionCase, tagged

from ..services.inbox_provider_mercadopago import MercadoPagoInboxProvider

COLLECTOR = "430185252"

QR_EXTERNAL = {
    "id": 170951482351, "status": "approved", "status_detail": "accredited",
    "collector_id": 430185252, "transaction_amount": 1500, "currency_id": "ARS",
    "date_approved": "2026-08-03T11:21:49.000-04:00",
    "payment_method_id": "interop_transfer", "pos_id": "64365871",
    "metadata": {"hide_payer_information": True},
    "payer": {"id": "1893987077"},
    "transaction_details": {"net_received_amount": 1477.5},
    "point_of_interaction": {
        "type": "INSTORE", "sub_type": "INTER_PSP",
        "business_info": {"unit": "wallet", "sub_unit": "qr", "branch": "QR"},
        "transaction_data": {"bank_info": {
            "payer": {"account_id": 1893987077,
                      "long_name": "Naranja Digital Compañia Financiera S.A."}}},
    },
}

QR_INTERNAL = {
    "id": 171858334766, "status": "approved", "status_detail": "accredited",
    "collector_id": 430185252, "transaction_amount": 100, "currency_id": "ARS",
    "date_approved": "2026-08-03T12:03:02.000-04:00",
    "payment_method_id": "account_money", "pos_id": "64365871",
    "metadata": {},
    "payer": {"id": "2429168801", "email": "erojasmontealegre@gmail.com",
              "identification": {"type": "CUIT", "number": "27964493338"}},
    "transaction_details": {"net_received_amount": 97.53},
    "point_of_interaction": {
        "type": "INSTORE", "sub_type": "INTRA_PSP",
        "business_info": {"unit": "wallet", "sub_unit": "qr", "branch": "QR"},
    },
}

ALIAS = {
    "id": 170951666839, "status": "approved", "status_detail": "accredited",
    "collector_id": 430185252, "transaction_amount": 1500, "currency_id": "ARS",
    "date_approved": "2026-08-03T11:22:50.000-04:00",
    "payment_method_id": "cvu", "metadata": {},
    "payer": {"id": "430185252", "email": "elbuscado8@gmail.com",
              "identification": {"type": "CUIT", "number": "20400321737"}},
    "transaction_details": {"net_received_amount": 1500},
    "point_of_interaction": {
        "type": "PSP_TRANSFER", "sub_type": "INTER_PSP",
        "business_info": {"unit": "digital_accounts_cards",
                          "sub_unit": "money_inflows", "branch": "null"},
    },
}

OUTGOING = {
    "id": 170057310398, "status": "approved", "status_detail": "accredited",
    "payer_id": 430185252, "collector": {"id": 2052122995},
    "transaction_amount": 535923.63, "currency_id": "ARS",
    "date_approved": "2026-07-22T17:00:24.000-04:00",
    "payment_method_id": "debin_transfer", "metadata": {},
    "point_of_interaction": {"type": "CHECKOUT",
        "business_info": {"unit": "credits", "sub_unit": "collections"}},
}


@tagged("post_install", "-at_install")
class TestNormalization(TransactionCase):
    def setUp(self):
        super().setUp()
        self.provider = MercadoPagoInboxProvider(client=None, mp_user_id=COLLECTOR)

    def test_outgoing_payment_is_not_ingestable(self):
        """Las compras propias del dueño no entran a la bandeja."""
        self.assertFalse(self.provider.is_ingestable(OUTGOING))

    def test_qr_and_alias_are_ingestable(self):
        """Los cobros por QR y por alias sí entran."""
        self.assertTrue(self.provider.is_ingestable(QR_EXTERNAL))
        self.assertTrue(self.provider.is_ingestable(QR_INTERNAL))
        self.assertTrue(self.provider.is_ingestable(ALIAS))

    def test_amount_is_gross_never_net(self):
        """Se guarda transaction_amount, no net_received_amount."""
        self.assertEqual(self.provider.normalize(QR_EXTERNAL)["amount"], 1500)
        self.assertEqual(self.provider.normalize(QR_INTERNAL)["amount"], 100)

    def test_external_wallet_gives_bank_not_identity(self):
        """INTER_PSP trae banco de origen y oculta la identificación."""
        row = self.provider.normalize(QR_EXTERNAL)
        self.assertEqual(row["source"], "qr")
        self.assertEqual(row["mp_pos_id"], "64365871")
        self.assertEqual(row["payer_bank_name"], "Naranja Digital Compañia Financiera S.A.")
        self.assertFalse(row["payer_vat"])
        self.assertEqual(row["mp_payer_id"], "1893987077")

    def test_mercadopago_wallet_gives_identity_not_bank(self):
        """INTRA_PSP trae CUIT y email reales, sin banco de origen."""
        row = self.provider.normalize(QR_INTERNAL)
        self.assertEqual(row["source"], "qr")
        self.assertEqual(row["payer_vat"], "27964493338")
        self.assertEqual(row["payer_email"], "erojasmontealegre@gmail.com")
        self.assertFalse(row["payer_bank_name"])

    def test_alias_never_persists_payer_identity(self):
        """En el canal alias el payer es el receptor: se descarta entero."""
        row = self.provider.normalize(ALIAS)
        self.assertEqual(row["source"], "alias")
        self.assertFalse(row["payer_vat"])
        self.assertFalse(row["payer_email"])
        self.assertFalse(row["mp_payer_id"])
        self.assertFalse(row["mp_pos_id"])
