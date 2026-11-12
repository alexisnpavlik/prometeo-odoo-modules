# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError

from .common import CcaCommon


class TestPaymentEdit(CcaCommon):

    def _confirmed(self, qty=1, count=1, first_due=date(2027, 2, 15), partner=None, **vals):
        """Retiro confirmado de `qty` × 100 en `count` cuotas."""
        withdrawal = self.env["cca.withdrawal"].create(dict({
            "partner_id": (partner or self.partner).id,
            "date": date(2026, 1, 15),
            "first_due_date": first_due,
            "installment_count": count,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": qty * 2})],
        }, **vals))
        withdrawal.action_confirm()
        return withdrawal

    def _pay(self, amount, partner=None, day=1):
        """Registra un pago del cliente."""
        return self.env["cca.payment"].create({
            "partner_id": (partner or self.partner).id,
            "amount": amount,
            "date": date(2026, 2, day),
        })

    def test_lower_amount_reallocates(self):
        """Bajar el monto devuelve deuda a la cuota."""
        withdrawal = self._confirmed(qty=2, count=2)
        payment = self._pay(150)
        payment.amount = 80
        first, second = withdrawal.installment_ids.sorted("sequence")
        self.assertEqual(payment.amount_allocated, 80.0)
        self.assertEqual(first.amount_residual, 20.0)
        self.assertEqual(second.amount_residual, 100.0)

    def test_higher_amount_covers_more(self):
        """Subir el monto cubre más cuotas y deja el sobrante como saldo a favor."""
        withdrawal = self._confirmed(qty=2, count=2)
        payment = self._pay(50)
        payment.amount = 230
        self.assertEqual(withdrawal.state, "paid")
        self.assertEqual(payment.amount_unallocated, 30.0)

    def test_lower_amount_uses_other_credit(self):
        """Lo que libera el pago editado lo cubre el saldo a favor de otro pago."""
        withdrawal = self._confirmed(qty=2, count=2)
        first_payment = self._pay(150, day=1)
        second_payment = self._pay(80, day=2)  # 50 a la cuota 2 + 30 a favor
        first_payment.amount = 100
        self.assertEqual(withdrawal.amount_residual, 20.0)
        self.assertEqual(second_payment.amount_unallocated, 0.0)

    def test_change_partner_moves_debt(self):
        """Cambiar el cliente pasa el pago a la cuenta correcta."""
        other = self.env["res.partner"].create({"name": "Otro cliente", "vat": "30999888"})
        mine = self._confirmed()
        theirs = self._confirmed(partner=other)
        payment = self._pay(100)
        self.assertEqual(mine.state, "paid")
        payment.partner_id = other
        self.assertEqual(payment.account_id.partner_id, other)
        self.assertEqual(mine.amount_residual, 100.0)
        self.assertEqual(theirs.state, "paid")

    def test_date_and_method_keep_allocations(self):
        """Fecha y medio de pago no tocan las imputaciones."""
        withdrawal = self._confirmed()
        payment = self._pay(100)
        allocations = payment.allocation_ids
        payment.write({"date": date(2026, 2, 10), "payment_method": "transfer"})
        self.assertEqual(payment.allocation_ids, allocations)
        self.assertEqual(withdrawal.state, "paid")

    def test_cancelled_payment_not_editable(self):
        """Un pago anulado no se edita."""
        self._confirmed()
        payment = self._pay(100)
        payment.action_cancel()
        with self.assertRaises(UserError):
            payment.amount = 50

    def test_down_payment_amount_locked(self):
        """La entrega inicial se cambia desde el retiro, no desde el pago."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "installment_count": 2,
            "down_payment": 40.0,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": 4})],
        })
        withdrawal.action_confirm()
        payment = withdrawal.down_payment_id
        self.assertTrue(payment.is_down_payment)
        with self.assertRaises(UserError):
            payment.amount = 60
        payment.payment_method = "card"
        self.assertEqual(payment.payment_method, "card")

    def test_warns_when_paying_several_installments(self):
        """Avisa si el monto cubre más de una cuota; con una sola no avisa."""
        self._confirmed(qty=2, count=2)
        account = self.env["cca.account"]._get_or_create(self.partner, self.env.company)
        new = self.env["cca.payment"].new({"partner_id": self.partner.id, "account_id": account.id, "amount": 150})
        self.assertIn("cubre 2 cuotas", new.multi_installment_warning)
        new.amount = 100
        self.assertFalse(new.multi_installment_warning)

    def test_withdrawal_lists_payments_and_undo(self):
        """El retiro lista sus pagos; anular uno devuelve la deuda."""
        withdrawal = self._confirmed(qty=2, count=2)
        payment = self._pay(200)
        self.assertEqual(withdrawal.payment_ids, payment)
        payment.action_cancel()
        self.assertFalse(withdrawal.payment_ids)
        self.assertEqual(withdrawal.amount_residual, 200.0)

    def test_down_payment_cannot_be_cancelled_alone(self):
        """La entrega inicial no se anula suelta."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "installment_count": 2,
            "down_payment": 40.0,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": 4})],
        })
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.down_payment_id.action_cancel()
