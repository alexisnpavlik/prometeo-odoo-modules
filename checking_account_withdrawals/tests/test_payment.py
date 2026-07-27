# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawPayment(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.company.caw_installment_count = 1
        self.company.caw_installment_days = 30
        self.company.caw_cutoff_day = 0
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _confirmed_withdrawal(self, total, date, count=1):
        """Crea y confirma un retiro con `count` cuotas."""
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date,
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })
        withdrawal._caw_check_confirmable()
        withdrawal._caw_generate_installments(count=count, first_days=30, period="months", cutoff_day=0)
        withdrawal.state = "pending"
        return withdrawal

    def _payment(self, amount):
        """Crea un pago en borrador sobre la cuenta del partner."""
        return self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": amount,
            "date": "2026-06-01",
            "payment_method": "cash",
        })

    def test_fifo_pays_oldest_installment_first(self):
        """El pago se imputa primero a la cuota con vencimiento más antiguo."""
        old = self._confirmed_withdrawal(100.0, "2026-01-01")
        new = self._confirmed_withdrawal(100.0, "2026-03-01")
        self._payment(100.0).action_post()
        self.assertEqual(old.installment_ids.amount_residual, 0.0)
        self.assertEqual(new.installment_ids.amount_residual, 100.0)

    def test_fifo_spans_multiple_withdrawals(self):
        """Un solo pago puede cubrir cuotas de varios retiros del mismo partner."""
        first = self._confirmed_withdrawal(100.0, "2026-01-01")
        second = self._confirmed_withdrawal(100.0, "2026-03-01")
        self._payment(150.0).action_post()
        self.assertEqual(first.installment_ids.amount_residual, 0.0)
        self.assertEqual(second.installment_ids.amount_residual, 50.0)

    def test_excess_becomes_credit_not_forced_allocation(self):
        """El sobrante no se fuerza contra ninguna cuota: queda como saldo a favor."""
        withdrawal = self._confirmed_withdrawal(100.0, "2026-01-01")
        payment = self._payment(300.0)
        payment.action_post()
        self.assertEqual(withdrawal.installment_ids.amount_allocated, 100.0)
        self.assertEqual(payment.amount_allocated, 100.0)
        self.assertEqual(payment.amount_unallocated, 200.0)

    def test_allocation_cannot_exceed_installment_residual(self):
        """No se puede imputar más que el residual de la cuota."""
        withdrawal = self._confirmed_withdrawal(100.0, "2026-01-01")
        payment = self._payment(500.0)
        payment.state = "posted"
        with self.assertRaises(ValidationError):
            self.env["caw.allocation"].create({
                "payment_id": payment.id,
                "installment_id": withdrawal.installment_ids.id,
                "amount": 150.0,
            })

    def test_allocation_cannot_exceed_payment_amount(self):
        """La suma de imputaciones no puede superar el monto del pago."""
        first = self._confirmed_withdrawal(100.0, "2026-01-01")
        second = self._confirmed_withdrawal(100.0, "2026-03-01")
        payment = self._payment(120.0)
        payment.action_post()
        with self.assertRaises(ValidationError):
            self.env["caw.allocation"].create({
                "payment_id": payment.id,
                "installment_id": second.installment_ids.id,
                "amount": 80.0,
            })

    def test_cancel_payment_reverts_allocations(self):
        """Anular un pago revierte sus imputaciones y las cuotas recalculan estado."""
        withdrawal = self._confirmed_withdrawal(100.0, "2026-01-01")
        payment = self._payment(100.0)
        payment.action_post()
        self.assertEqual(withdrawal.installment_ids.state, "paid")
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")
        self.assertFalse(payment.allocation_ids)
        self.assertEqual(withdrawal.installment_ids.amount_allocated, 0.0)

    def test_payment_amount_must_be_positive(self):
        """Un pago con monto menor o igual a cero no se publica."""
        payment = self._payment(0.0)
        with self.assertRaises(UserError):
            payment.action_post()
