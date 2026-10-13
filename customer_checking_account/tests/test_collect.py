# -*- coding: utf-8 -*-
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields

from .common import CcaCommon


class TestCollect(CcaCommon):

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

    def _pay(self, amount):
        """Pago del cliente de prueba."""
        return self.env["cca.payment"].create({"partner_id": self.partner.id, "amount": amount})

    # --- Anular un pago reimputa el saldo a favor de otros pagos ---

    def test_cancel_payment_reallocates_other_credit(self):
        """Si se anula un pago, el saldo a favor de otro pago cubre lo que quedó abierto."""
        withdrawal = self._confirmed()          # debe 100
        first = self._pay(100)                  # lo cancela
        second = self._pay(50)                  # queda todo como saldo a favor
        self.assertEqual(second.amount_unallocated, 50.0)
        first.action_cancel()
        self.assertEqual(second.amount_unallocated, 0.0)
        self.assertEqual(withdrawal.amount_residual, 50.0)
        self.assertEqual(withdrawal.state, "partial")

    # --- Comprobante ---

    def test_receipt_renders_payment_details(self):
        """El comprobante muestra cliente, monto, cuota cubierta y saldo pendiente."""
        withdrawal = self._confirmed(qty=6, count=3)   # 3 cuotas de 100
        payment = self._pay(150)
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "customer_checking_account.action_report_cca_payment_receipt", payment.ids
        )
        html = html.decode()
        self.assertIn("Cliente CCA Test", html)
        self.assertIn("30111222", html)
        self.assertIn(withdrawal.name, html)
        self.assertIn("1/3", html)
        self.assertIn("2/3", html)
        self.assertIn("150", html)
        self.assertIn("Saldo pendiente", html)

    def test_payment_has_print_receipt_action(self):
        """El pago tiene una acción para imprimir el comprobante."""
        self._confirmed()
        payment = self._pay(10)
        action = payment.action_print_receipt()
        self.assertEqual(action["report_name"], "customer_checking_account.report_cca_payment_receipt")

    # --- Para cobrar ---

    def test_collect_button_on_installment(self):
        """El botón Cobrar de una cuota abre el pago con su saldo."""
        withdrawal = self._confirmed(qty=4, count=2)
        installment = withdrawal.installment_ids.sorted("sequence")[0]
        action = installment.action_register_payment()
        self.assertEqual(action["res_model"], "cca.payment")
        self.assertEqual(action["context"]["default_partner_id"], self.partner.id)
        self.assertEqual(action["context"]["default_amount"], 100.0)

    def test_to_collect_filter_covers_overdue_and_this_week(self):
        """El filtro 'Para cobrar' trae vencidas y las que vencen en 7 días, no las lejanas."""
        today = fields.Date.context_today(self.env.user)
        overdue = self._confirmed(first_due=date(2026, 2, 1))
        soon = self._confirmed(first_due=today + relativedelta(days=3))
        later = self._confirmed(first_due=today + relativedelta(days=30))
        found = self.env["cca.installment"].search(
            self.env["cca.installment"]._cca_to_collect_domain()
        )
        self.assertIn(overdue.installment_ids, found)
        self.assertIn(soon.installment_ids, found)
        self.assertNotIn(later.installment_ids, found)
