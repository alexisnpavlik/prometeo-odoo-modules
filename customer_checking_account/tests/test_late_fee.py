# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields

from .common import CcaCommon


class TestLateFee(CcaCommon):

    def setUp(self):
        super().setUp()
        self.today = fields.Date.context_today(self.env.user)

    def _confirmed(self, days_overdue, qty=20, **vals):
        """Retiro de qty × 50 en una cuota vencida hace `days_overdue` días."""
        due = self.today - relativedelta(days=days_overdue)
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": due - relativedelta(days=30),
            "first_due_date": due,
            "late_fee_enabled": True,
            "late_fee_daily_amount": 500.0,
            "late_fee_grace_days": 5,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": qty})],
            **vals,
        })
        withdrawal.action_confirm()
        return withdrawal

    def _run_cron(self):
        """Corre el cron diario de vencidas y mora."""
        self.env["cca.installment"]._cron_update_overdue()

    def test_fee_accrues_per_day_after_grace(self):
        """13 días vencida con 5 de gracia: 8 días × 500 = 4000, y suma a la deuda."""
        withdrawal = self._confirmed(13)
        self._run_cron()
        installment = withdrawal.installment_ids
        self.assertEqual(installment.late_fee, 4000.0)
        self.assertEqual(installment.amount_residual, 5000.0)
        self.assertEqual(withdrawal.amount_residual, 5000.0)
        self.assertEqual(withdrawal.account_id.balance, 5000.0)

    def test_no_fee_within_grace(self):
        """Dentro de los días de gracia no hay mora."""
        withdrawal = self._confirmed(5)
        self._run_cron()
        self.assertEqual(withdrawal.installment_ids.late_fee, 0.0)

    def test_no_fee_when_disabled(self):
        """Con la casilla apagada no se cobra mora."""
        withdrawal = self._confirmed(30, late_fee_enabled=False)
        self._run_cron()
        self.assertEqual(withdrawal.installment_ids.late_fee, 0.0)

    def test_payment_covers_fee_and_stops_accrual(self):
        """El pago cubre capital y mora; pagada la cuota, la mora deja de crecer."""
        withdrawal = self._confirmed(13)
        self._run_cron()
        self.env["cca.payment"].create({"partner_id": self.partner.id, "amount": 5000})
        installment = withdrawal.installment_ids
        self.assertEqual(installment.state, "paid")
        self.assertEqual(withdrawal.state, "paid")
        # Al día siguiente la cuota pagada no suma más mora.
        self.env["cca.installment"].with_context(
            cca_today=self.today + relativedelta(days=1)
        )._cron_update_overdue()
        self.assertEqual(installment.late_fee, 4000.0)

    def test_payment_updates_fee_before_allocating(self):
        """Sin esperar al cron, el pago calcula la mora del día antes de imputar."""
        withdrawal = self._confirmed(13)
        payment = self.env["cca.payment"].create({"partner_id": self.partner.id, "amount": 5000})
        self.assertEqual(withdrawal.installment_ids.late_fee, 4000.0)
        self.assertEqual(payment.amount_unallocated, 0.0)

    def test_late_fee_disabled_by_default_on_withdrawal(self):
        """La mora viene desactivada por defecto: se activa a mano en cada retiro."""
        withdrawal = self.env["cca.withdrawal"].create({"partner_id": self.partner.id})
        self.assertFalse(withdrawal.late_fee_enabled)

    def test_each_withdrawal_has_its_own_rate(self):
        """Cada retiro usa su propio monto por día."""
        cheap = self._confirmed(13, late_fee_daily_amount=100.0)
        self._run_cron()
        self.assertEqual(cheap.installment_ids.late_fee, 800.0)
