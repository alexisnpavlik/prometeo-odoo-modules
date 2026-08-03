from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAprobacionManual(TransactionCase):
    """Registro auditado de cobros marcados como recibidos sin verificar el pago."""

    def setUp(self):
        """Arma cuenta y método en una compañía activa, explícita.

        En esta base la compañía del superusuario (id 1) está archivada: un
        método de pago creado con ella no es legible por ningún usuario de
        prueba (ver `test_reserva_por_uuid.py`).
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

    def test_reason_is_mandatory(self):
        """Sin motivo no hay aprobación manual."""
        with self.assertRaises(UserError):
            self.method.register_manual_approval("uuid-1", "   ")

    def test_approval_records_who_and_when(self):
        """Queda registrado usuario, motivo y momento."""
        self.method.register_manual_approval("uuid-1", "El cliente ya se iba")
        approval = self.env["mercadopago.manual.approval"].search([
            ("pos_payment_uuid", "=", "uuid-1")
        ])
        self.assertEqual(len(approval), 1)
        self.assertEqual(approval.user_id, self.env.user)
        self.assertEqual(approval.reason, "El cliente ya se iba")
        self.assertTrue(approval.create_date)

    def test_creating_the_payment_line_completes_the_approval(self):
        """Al sincronizarse la orden, la aprobación queda con monto, venta y sesión.

        `register_manual_approval()` sólo conoce el uuid del navegador; recién
        cuando `pos.payment.create()` corre existe un `pos.payment` real. Sin
        este cierre el reporte de aprobaciones manuales -el control que
        justifica la existencia del modelo- saldría sin plata ni venta.
        """
        self.method.register_manual_approval("uuid-1", "El cliente ya se iba")

        config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja test aprobación manual", "company_id": self.company.id,
        })
        config.write({"payment_method_ids": [(4, self.method.id)]})
        config.open_ui()
        order = self.env["pos.order"].create({
            "session_id": config.current_session_id.id, "amount_total": 1500.0,
            "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
        })
        line = self.env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": self.method.id,
            "amount": 1500.0, "mercadopago_uuid": "uuid-1",
        })

        approval = self.env["mercadopago.manual.approval"].search([
            ("pos_payment_uuid", "=", "uuid-1")
        ])
        self.assertEqual(approval.pos_payment_id, line)
        self.assertEqual(approval.pos_order_id, order)
        self.assertEqual(approval.pos_session_id, order.session_id)
        self.assertEqual(approval.amount, 1500.0)

        self.assertTrue(line.is_manual_approval)
        self.assertEqual(line.manual_reason, "El cliente ya se iba")
        self.assertEqual(line.manual_approved_by_user_id, self.env.user)
        self.assertTrue(line.manual_approved_at)
