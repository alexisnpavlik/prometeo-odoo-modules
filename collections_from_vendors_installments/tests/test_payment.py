# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviPayment(CviCommon):

    def setUp(self):
        super().setUp()
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_12.id,
            "charge_day_month": 10,
        })
        self.card._cvi_generate_installments()

    def _pay(self, amount, **kwargs):
        """Cobro publicado sobre la tarjeta de test."""
        vals = {"card_id": self.card.id, "amount": amount, "date": "2026-02-10"}
        vals.update(kwargs)
        payment = self.env["cvi.payment"].create(vals)
        payment.action_post()
        return payment

    def _installment(self, sequence):
        return self.card.installment_ids.filtered(lambda i: i.sequence == sequence)

    def test_payment_gets_sequence_reference(self):
        """El cobro recibe una referencia de la secuencia."""
        payment = self._pay(10000.0)
        self.assertTrue(payment.name.startswith("COB/"))

    def test_posting_sets_state_posted(self):
        """Publicar un cobro lo deja en estado Registrado."""
        self.assertEqual(self._pay(10000.0).state, "posted")

    def test_exact_installment_payment_marks_it_paid(self):
        """Un cobro por el importe exacto de una cuota la deja pagada."""
        self._pay(10000.0)
        self.assertEqual(self._installment(2).state, "paid")
        self.assertEqual(self._installment(2).amount_residual, 0.0)

    def test_partial_payment_leaves_installment_partial(self):
        """Un cobro por menos del importe deja la cuota parcial con residual."""
        self._pay(4000.0)
        second = self._installment(2)
        self.assertEqual(second.state, "partial")
        self.assertEqual(second.amount_paid, 4000.0)
        self.assertEqual(second.amount_residual, 6000.0)

    def test_payment_covers_multiple_installments(self):
        """Un cobro grande cubre varias cuotas de una sola vez."""
        self._pay(25000.0)
        self.assertEqual(self._installment(2).state, "paid")
        self.assertEqual(self._installment(3).state, "paid")
        self.assertEqual(self._installment(4).state, "partial")
        self.assertEqual(self._installment(4).amount_paid, 5000.0)

    def test_allocation_is_fifo_by_due_date(self):
        """La imputación arranca por la cuota de cobranza más vieja impaga."""
        self._pay(10000.0)
        allocated = self._pay(10000.0).allocation_ids
        self.assertEqual(len(allocated), 1)
        self.assertEqual(allocated.installment_id.sequence, 3)

    def test_commission_payment_only_hits_commission_installment(self):
        """El cobro de comisión imputa sobre la cuota 1, no sobre las de cobranza."""
        payment = self._pay(10000.0, is_commission=True, date="2026-01-15")
        self.assertEqual(payment.allocation_ids.installment_id.sequence, 1)
        self.assertEqual(self._installment(1).state, "paid")
        self.assertEqual(self._installment(2).state, "pending")

    def test_regular_payment_never_hits_commission_installment(self):
        """Un cobro normal saltea la cuota del vendedor aunque esté impaga (HU-09)."""
        payment = self._pay(10000.0)
        self.assertEqual(payment.allocation_ids.installment_id.sequence, 2)
        self.assertEqual(self._installment(1).state, "pending")

    def test_overpayment_is_rejected(self):
        """No se acepta un cobro que supera lo que la tarjeta adeuda."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 999999.0, "date": "2026-02-10",
        })
        with self.assertRaises(UserError):
            payment.action_post()

    def test_posting_twice_is_rejected(self):
        """Un cobro ya publicado no se vuelve a publicar."""
        payment = self._pay(10000.0)
        with self.assertRaises(UserError):
            payment.action_post()

    def test_cancel_releases_the_installment(self):
        """Anular un cobro devuelve la cuota a pendiente (RN-06)."""
        payment = self._pay(10000.0)
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")
        self.assertFalse(payment.allocation_ids)
        self.assertEqual(self._installment(2).amount_paid, 0.0)

    def test_cancelled_payment_keeps_its_record(self):
        """El cobro anulado sigue existiendo con su monto y su usuario (RN-06)."""
        payment = self._pay(10000.0)
        payment.action_cancel()
        self.assertTrue(payment.exists())
        self.assertEqual(payment.amount, 10000.0)
        self.assertEqual(payment.user_id, self.env.user)

    def test_payment_cannot_be_deleted(self):
        """Un cobro publicado no se puede borrar, ni siquiera por el administrador."""
        payment = self._pay(10000.0)
        with self.assertRaises(UserError):
            payment.unlink()

    def test_draft_payment_can_be_deleted(self):
        """Un cobro en borrador (todavía sin publicar) sí se puede descartar."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 5000.0, "date": "2026-02-10",
        })
        payment.unlink()
        self.assertFalse(payment.exists())

    def test_payment_records_who_charged(self):
        """Queda registrado quién cobró y cuándo (RN-06, RN-08)."""
        payment = self._pay(10000.0)
        self.assertEqual(payment.user_id, self.env.user)
        self.assertEqual(str(payment.date), "2026-02-10")
