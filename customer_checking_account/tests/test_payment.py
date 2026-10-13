# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError, ValidationError

from .common import CcaCommon


class TestPayment(CcaCommon):

    def _confirmed(self, qty=1, count=1, first_due=date(2027, 2, 15), **vals):
        """Retiro confirmado de `qty` × 100 en `count` cuotas."""
        withdrawal = self.env["cca.withdrawal"].create(dict({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": first_due,
            "installment_count": count,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": qty * 2})],
        }, **vals))
        withdrawal.action_confirm()
        return withdrawal

    def _pay(self, amount, account):
        """Registra un pago."""
        return self.env["cca.payment"].create({
            "account_id": account.id,
            "amount": amount,
            "date": date(2026, 2, 1),
        })

    def test_payment_posted_on_create(self):
        """El pago queda registrado sin pasos extra y con número."""
        withdrawal = self._confirmed()
        payment = self._pay(40, withdrawal.account_id)
        self.assertEqual(payment.state, "posted")
        self.assertTrue(payment.name.startswith("RCP/"))

    def test_partial_payment_fifo_oldest_first(self):
        """Un pago parcial va a la cuota más vieja del cliente."""
        older = self._confirmed(first_due=date(2027, 2, 1))
        newer = self._confirmed(first_due=date(2027, 3, 1))
        self._pay(60, older.account_id)
        self.assertEqual(older.amount_residual, 40.0)
        self.assertEqual(older.state, "partial")
        self.assertEqual(newer.amount_residual, 100.0)

    def test_payment_spans_installments(self):
        """Un pago que cubre una cuota y parte de la siguiente."""
        withdrawal = self._confirmed(qty=2, count=2)  # 2 cuotas de 100
        self._pay(150, withdrawal.account_id)
        first, second = withdrawal.installment_ids.sorted("sequence")
        self.assertEqual(first.state, "paid")
        self.assertEqual(second.amount_residual, 50.0)

    def test_full_payment_marks_paid(self):
        """Pagar todo deja el retiro pagado."""
        withdrawal = self._confirmed()
        self._pay(100, withdrawal.account_id)
        self.assertEqual(withdrawal.state, "paid")
        self.assertEqual(withdrawal.account_id.balance, 0.0)

    def test_overpayment_leaves_credit(self):
        """El sobrante queda como saldo a favor."""
        withdrawal = self._confirmed()
        payment = self._pay(130, withdrawal.account_id)
        self.assertEqual(payment.amount_unallocated, 30.0)
        self.assertEqual(withdrawal.account_id.credit_balance, 30.0)

    def test_credit_applied_on_confirm(self):
        """Al confirmar un retiro nuevo se le imputa el saldo a favor."""
        first = self._confirmed()
        self._pay(130, first.account_id)
        second = self._confirmed()
        self.assertEqual(second.amount_residual, 70.0)
        self.assertEqual(first.account_id.credit_balance, 0.0)

    def test_cancel_payment_reverts_allocations(self):
        """Anular un pago devuelve la deuda."""
        withdrawal = self._confirmed()
        payment = self._pay(100, withdrawal.account_id)
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")
        self.assertEqual(withdrawal.amount_residual, 100.0)
        self.assertEqual(withdrawal.state, "pending")

    def test_non_positive_amount_rejected(self):
        """El monto tiene que ser mayor a cero."""
        withdrawal = self._confirmed()
        with self.assertRaises(ValidationError):
            self._pay(0, withdrawal.account_id)

    def test_cannot_cancel_withdrawal_with_payments(self):
        """Un retiro con pagos imputados no se cancela."""
        withdrawal = self._confirmed()
        self._pay(10, withdrawal.account_id)
        with self.assertRaises(UserError):
            withdrawal.action_cancel()

    def test_cron_marks_overdue(self):
        """El cron marca vencida una cuota impaga con fecha pasada."""
        withdrawal = self._confirmed(first_due=date(2027, 2, 1))
        installment = withdrawal.installment_ids
        # Posterior a la fecha del retiro (2026-01-15) y anterior a hoy.
        installment.with_context(cca_skip_total_check=True).date_due = date(2026, 2, 1)
        self.env["cca.installment"]._cron_update_overdue()
        self.assertEqual(installment.state, "overdue")
        self.assertTrue(withdrawal.is_overdue)
