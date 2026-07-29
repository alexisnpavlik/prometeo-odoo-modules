# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawWithdrawalState(CawCommon):
    """Casos obligatorios de CC-31: el falso pagado total no debe poder ocurrir."""

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _confirmed(self, total, count):
        """Retiro confirmado por `total` con `count` cuotas iguales."""
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })
        withdrawal._caw_generate_installments(
            count=count, first_days=30, period="months", cutoff_day=0
        )
        return withdrawal

    def _posted_payment(self, amount):
        """Pago publicado sin imputación automática (para imputar a mano)."""
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": amount,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        payment.state = "posted"
        return payment

    def _allocate(self, payment, installment, amount):
        """Imputa manualmente un monto de un pago a una cuota."""
        return self.env["caw.allocation"].create({
            "payment_id": payment.id,
            "installment_id": installment.id,
            "amount": amount,
        })

    def test_pending_when_no_allocation(self):
        """Sin ninguna imputación el retiro está pendiente."""
        withdrawal = self._confirmed(600.0, 3)
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(withdrawal.amount_residual, 600.0)

    def test_partial_when_some_allocation(self):
        """Con imputación parcial el retiro queda en parcial."""
        withdrawal = self._confirmed(600.0, 3)
        payment = self._posted_payment(200.0)
        self._allocate(payment, withdrawal.installment_ids.sorted("sequence")[0], 200.0)
        self.assertEqual(withdrawal.state, "partial")

    def test_paid_only_when_every_installment_is_paid(self):
        """El retiro pasa a pagado únicamente con todas las cuotas canceladas."""
        withdrawal = self._confirmed(600.0, 3)
        payment = self._posted_payment(600.0)
        for installment in withdrawal.installment_ids:
            self._allocate(payment, installment, installment.amount)
        self.assertEqual(withdrawal.state, "paid")
        self.assertEqual(withdrawal.amount_residual, 0.0)

    def test_five_of_six_installments_paid_is_never_paid(self):
        """CC-31: retiro de 6 cuotas con 5 canceladas → parcial, nunca pagado."""
        withdrawal = self._confirmed(600.0, 6)
        installments = withdrawal.installment_ids.sorted("sequence")
        payment = self._posted_payment(500.0)
        for installment in installments[:5]:
            self._allocate(payment, installment, installment.amount)
        self.assertEqual(withdrawal.state, "partial")
        self.assertNotEqual(withdrawal.state, "paid")
        self.assertGreater(withdrawal.amount_residual, 0.0)

    def test_overpay_first_underpay_second_stays_partial(self):
        """CC-31: total imputado = total del retiro pero con una cuota abierta → parcial.

        La cuota 1 no puede recibir más que su residual, así que el excedente queda
        sin imputar. El retiro NUNCA debe cerrarse por coincidencia de montos.
        """
        withdrawal = self._confirmed(200.0, 2)
        installments = withdrawal.installment_ids.sorted("sequence")
        payment = self._posted_payment(200.0)
        self._allocate(payment, installments[0], 100.0)
        self._allocate(payment, installments[1], 60.0)
        self.assertEqual(installments[0].state, "paid")
        self.assertEqual(installments[1].amount_residual, 40.0)
        self.assertEqual(withdrawal.state, "partial")

    def test_constraint_blocks_manual_paid_with_open_installments(self):
        """El constraint rechaza forzar 'paid' con alguna cuota con residual > 0."""
        withdrawal = self._confirmed(600.0, 3)
        with self.assertRaises(ValidationError):
            withdrawal.with_context(caw_skip_state_compute=True).write({"state": "paid"})
            withdrawal.flush_recordset()

    def test_cancelling_payment_reverts_paid_to_partial(self):
        """Anular un pago devuelve el retiro de pagado a parcial."""
        withdrawal = self._confirmed(200.0, 2)
        installments = withdrawal.installment_ids.sorted("sequence")
        payment = self._posted_payment(200.0)
        for installment in installments:
            self._allocate(payment, installment, installment.amount)
        self.assertEqual(withdrawal.state, "paid")
        payment.action_cancel()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(withdrawal.amount_residual, 200.0)

    def test_overdue_flag_is_independent_of_state(self):
        """Un retiro puede estar parcial y en mora a la vez."""
        withdrawal = self._confirmed(200.0, 2)
        installments = withdrawal.installment_ids.sorted("sequence")
        installments[0].date_due = "2026-01-02"
        payment = self._posted_payment(50.0)
        self._allocate(payment, installments[0], 50.0)
        withdrawal.invalidate_recordset()
        self.assertEqual(withdrawal.state, "partial")
        self.assertTrue(withdrawal.is_overdue)
