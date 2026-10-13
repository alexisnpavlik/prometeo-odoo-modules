# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import Form

from .common import CcaCommon


class TestDownPayment(CcaCommon):

    def _withdrawal(self, qty=20, down=200.0, surcharge=10.0, count=3, product=None, **vals):
        """Retiro de qty × 50 con entrega inicial y recargo."""
        values = {
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "installment_count": count,
            "surcharge_percent": surcharge,
            "down_payment": down,
            "down_payment_method": "transfer",
            "line_ids": [(0, 0, {"product_id": (product or self.service).id, "quantity": qty})],
        }
        values.update(vals)
        return self.env["cca.withdrawal"].create(values)

    def test_surcharge_applies_to_financed_amount(self):
        """El recargo va sobre lo financiado: (1000 - 200) × 10% = 80; total 1080."""
        withdrawal = self._withdrawal()
        self.assertEqual(withdrawal.amount_untaxed, 1000.0)
        self.assertEqual(withdrawal.amount_surcharge, 80.0)
        self.assertEqual(withdrawal.amount_total, 1080.0)
        self.assertEqual(withdrawal.amount_financed, 880.0)

    def test_installments_include_down_payment_row(self):
        """La entrega es la fila 0, vence el día del retiro; el resto se reparte en cuotas."""
        withdrawal = self._withdrawal()
        installments = withdrawal.installment_ids.sorted("sequence")
        self.assertEqual(len(installments), 4)
        down = installments[0]
        self.assertTrue(down.is_down_payment)
        self.assertEqual(down.amount, 200.0)
        self.assertEqual(down.date_due, date(2026, 1, 15))
        self.assertAlmostEqual(sum(installments[1:].mapped("amount")), 880.0)

    def test_onchange_preview_with_down_payment(self):
        """En el formulario, la entrega descuenta lo financiado en vivo."""
        form = Form(self.env["cca.withdrawal"])
        form.partner_id = self.partner
        form.first_due_date = date(2027, 2, 15)
        with form.line_ids.new() as line:
            line.product_id = self.service
            line.quantity = 20
        form.surcharge_percent = 10.0
        form.installment_count = 2
        form.down_payment = 200.0
        self.assertEqual(form.amount_total, 1080.0)
        self.assertEqual(len(form.installment_ids), 3)
        self.assertEqual(form.installment_ids._records[1]["amount"], 440.0)

    def test_confirm_records_down_payment_on_this_withdrawal(self):
        """Confirmar registra la entrega como pago imputado solo a la fila de entrega."""
        older = self._withdrawal(down=0.0, surcharge=0.0, count=1, qty=2,
                                 first_due_date=date(2026, 2, 1))      # deuda vieja vencida
        older.action_confirm()
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        payment = withdrawal.down_payment_id
        self.assertEqual(payment.state, "posted")
        self.assertEqual(payment.amount, 200.0)
        self.assertEqual(payment.payment_method, "transfer")
        self.assertEqual(payment.allocation_ids.installment_id.is_down_payment, True)
        self.assertEqual(payment.allocation_ids.withdrawal_id, withdrawal)
        self.assertEqual(older.amount_residual, 100.0)
        self.assertEqual(withdrawal.amount_residual, 880.0)
        self.assertEqual(withdrawal.state, "partial")

    def test_down_payment_cannot_exceed_subtotal(self):
        """La entrega no puede superar el subtotal ni ser negativa."""
        with self.assertRaises(ValidationError):
            self._withdrawal(down=1500.0)
        with self.assertRaises(ValidationError):
            self._withdrawal(down=-1.0)

    def test_full_down_payment_is_paid(self):
        """Si la entrega cubre todo, al confirmar queda pagado y sin cuotas."""
        withdrawal = self._withdrawal(down=1000.0)
        self.assertEqual(withdrawal.amount_total, 1000.0)
        self.assertEqual(len(withdrawal.installment_ids), 1)
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "paid")

    def test_cancel_with_only_down_payment_voids_it(self):
        """Devolver un retiro cuyo único pago es la entrega anula ese pago."""
        withdrawal = self._withdrawal(product=self.product, qty=10)
        withdrawal.action_confirm()
        payment = withdrawal.down_payment_id
        self.assertFalse(withdrawal.cca_has_payments)
        withdrawal.action_cancel()
        self.assertEqual(withdrawal.state, "cancel")
        self.assertEqual(payment.state, "cancel")

    def test_edit_with_only_down_payment_returns_to_draft(self):
        """Editar con solo la entrega vuelve a borrador; al reconfirmar hay entrega nueva."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        first_payment = withdrawal.down_payment_id
        withdrawal.action_edit()
        self.assertEqual(withdrawal.state, "draft")
        self.assertEqual(first_payment.state, "cancel")
        withdrawal.down_payment = 300.0
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.down_payment_id.amount, 300.0)
        self.assertNotEqual(withdrawal.down_payment_id, first_payment)

    def test_edit_with_other_payments_only_due_dates(self):
        """Con pagos además de la entrega, Editar solo habilita vencimientos."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        self.env["cca.payment"].create({"partner_id": self.partner.id, "amount": 50})
        self.assertTrue(withdrawal.cca_has_payments)
        withdrawal.action_edit()
        self.assertTrue(withdrawal.edit_due_dates)
        self.assertNotEqual(withdrawal.state, "draft")
