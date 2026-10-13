# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests import Form

from .common import CcaCommon


class TestPaymentUx(CcaCommon):

    def _confirmed(self, qty=2, count=1, first_due=date(2027, 2, 15)):
        """Retiro confirmado de servicios (qty × 50)."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": first_due,
            "installment_count": count,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": qty})],
        })
        withdrawal.action_confirm()
        return withdrawal

    def test_payment_by_partner_resolves_account(self):
        """El pago se carga por cliente y la cuenta se resuelve sola."""
        withdrawal = self._confirmed()
        payment = self.env["cca.payment"].create({"partner_id": self.partner.id, "amount": 40})
        self.assertEqual(payment.account_id, withdrawal.account_id)
        self.assertEqual(withdrawal.amount_residual, 60.0)

    def test_form_shows_debt_and_quick_amounts(self):
        """Elegido el cliente se ve la deuda, y los atajos completan el monto."""
        self._confirmed(qty=4, count=2)  # 2 cuotas de 100
        overdue = self._confirmed(qty=2, first_due=date(2026, 2, 1))  # 100 vencido
        form = Form(self.env["cca.payment"])
        form.partner_id = self.partner
        self.assertEqual(form.account_balance, 300.0)
        self.assertEqual(form.account_overdue_balance, 100.0)
        form.quick_amount = "overdue"
        self.assertEqual(form.amount, 100.0)
        form.quick_amount = "all"
        self.assertEqual(form.amount, 300.0)
        self.assertTrue(overdue)

    def test_preview_lists_installments_and_surplus(self):
        """La vista previa muestra qué cubre el pago y avisa el saldo a favor."""
        withdrawal = self._confirmed(qty=4, count=2)
        form = Form(self.env["cca.payment"])
        form.partner_id = self.partner
        form.amount = 150
        self.assertIn(withdrawal.name, form.allocation_preview)
        self.assertNotIn("saldo a favor", form.allocation_preview)
        form.amount = 250
        self.assertIn("saldo a favor", form.allocation_preview)

    def test_preview_matches_real_allocation(self):
        """Lo que muestra la vista previa es lo que se imputa al guardar."""
        withdrawal = self._confirmed(qty=4, count=2)
        plan, rest = withdrawal.account_id._cca_fifo_plan(150)
        self.assertEqual([amount for _i, amount in plan], [100.0, 50.0])
        self.assertEqual(rest, 0.0)
        payment = self.env["cca.payment"].create({"partner_id": self.partner.id, "amount": 150})
        self.assertEqual(sorted(payment.allocation_ids.mapped("amount")), [50.0, 100.0])

    def test_register_payment_from_withdrawal(self):
        """El botón del retiro abre el pago con cliente y saldo del retiro."""
        withdrawal = self._confirmed()
        action = withdrawal.action_register_payment()
        self.assertEqual(action["res_model"], "cca.payment")
        self.assertEqual(action["context"]["default_partner_id"], self.partner.id)
        self.assertEqual(action["context"]["default_amount"], 100.0)

    def test_register_payment_from_account(self):
        """El botón de la cuenta abre el pago por la deuda total."""
        withdrawal = self._confirmed(qty=4)
        action = withdrawal.account_id.action_register_payment()
        self.assertEqual(action["context"]["default_amount"], 200.0)
