from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReservaAImputacion(TransactionCase):
    """Cierre de la reserva por uuid (Task 11) al crearse el pos.payment real."""

    def setUp(self):
        """Arma cuenta, método y una reserva ya hecha, en una compañía activa.

        En `calidad` la compañía id 1 está archivada: crear todo explícitamente
        en una compañía activa evita romper contra la regla multiempresa, igual
        que en test_reserva_por_uuid.py.
        """
        super().setUp()
        self.company = self.env["res.company"].search([], limit=1)
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=self.company.ids))
        self.account = self.env["mercadopago.account"].with_company(self.company).create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
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
        self.config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja test cierre reserva", "company_id": self.company.id,
        })
        self.config.write({"payment_method_ids": [(4, self.method.id)]})
        self.config.open_ui()
        self.session = self.config.current_session_id
        self.payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351", "account_id": self.account.id,
            "amount": 1500.0, "date_approved": fields.Datetime.now(),
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })

    def _order(self):
        """Crea una orden vacía sobre la sesión abierta de la caja de prueba."""
        return self.env["pos.order"].create({
            "session_id": self.session.id, "amount_total": 1500.0, "amount_tax": 0,
            "amount_paid": 0, "amount_return": 0,
        })

    def test_reserved_payment_links_on_line_creation(self):
        """Al crearse el pos.payment con ese uuid, la reserva se convierte en imputación."""
        self.payment.reserve_for_uuid("uuid-abc")
        self.assertEqual(self.payment.state, "matched")
        self.assertFalse(self.payment.pos_payment_id)

        line = self.env["pos.payment"].create({
            "pos_order_id": self._order().id,
            "payment_method_id": self.method.id,
            "amount": 1500.0,
            "mercadopago_uuid": "uuid-abc",
        })

        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.pos_payment_id, line)
        self.assertEqual(self.payment.pos_session_id, self.session)
        self.assertEqual(self.payment.amount_difference, 0.0)
        self.assertEqual(line.mercadopago_payment_id, self.payment)

    def test_line_without_reservation_is_untouched(self):
        """Una línea sin uuid reservado no toca la bandeja."""
        line = self.env["pos.payment"].create({
            "pos_order_id": self._order().id,
            "payment_method_id": self.method.id,
            "amount": 1500.0,
        })
        self.assertFalse(line.mercadopago_payment_id)
        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.state, "available")

    def test_line_with_uuid_but_no_reservation_does_not_break_the_sale(self):
        """Un uuid sin reserva asociada se loguea y no rompe la creación de la venta."""
        line = self.env["pos.payment"].create({
            "pos_order_id": self._order().id,
            "payment_method_id": self.method.id,
            "amount": 1500.0,
            "mercadopago_uuid": "uuid-que-no-existe",
        })
        self.assertTrue(line.id)
        self.assertFalse(line.mercadopago_payment_id)

    def test_load_pos_data_fields_exposes_the_uuid(self):
        """El POS necesita sincronizar mercadopago_uuid para poder cerrar la reserva."""
        fields_list = self.env["pos.payment"]._load_pos_data_fields(self.config.id)
        self.assertIn("mercadopago_uuid", fields_list)
