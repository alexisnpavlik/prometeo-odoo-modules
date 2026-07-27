# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawBalance(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _confirmed(self, total, count=1, date="2026-01-01"):
        """Retiro confirmado por `total` con `count` cuotas."""
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date,
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

    def test_balance_sums_open_residuals(self):
        """El saldo suma únicamente residuales de cuotas no canceladas."""
        self._confirmed(500.0)
        self._confirmed(300.0)
        self.account.invalidate_recordset()
        self.assertEqual(self.account.balance, 800.0)

    def test_draft_withdrawals_do_not_count(self):
        """Un retiro en borrador no suma al saldo."""
        self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 999.0,
            })],
        })
        self.account.invalidate_recordset()
        self.assertEqual(self.account.balance, 0.0)

    def test_overdue_balance_counts_only_past_due(self):
        """El vencido cuenta solo cuotas impagas con vencimiento anterior a hoy."""
        withdrawal = self._confirmed(400.0, count=2)
        installments = withdrawal.installment_ids.sorted("sequence")
        installments[0].date_due = "2026-01-02"
        installments[1].date_due = "2027-01-01"
        self.env["caw.installment"]._cron_update_overdue()
        self.account.invalidate_recordset()
        self.assertEqual(self.account.balance, 400.0)
        self.assertEqual(self.account.overdue_balance, 200.0)

    def test_credit_balance_reflects_unallocated_payments(self):
        """El sobrante de los pagos publicados es el saldo a favor de la cuenta."""
        self._confirmed(100.0)
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": 250.0,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        payment.action_post()
        self.account.invalidate_recordset()
        self.assertEqual(self.account.credit_balance, 150.0)
        self.assertEqual(self.account.balance, 0.0)

    def test_partner_fields_aggregate_accounts(self):
        """Los campos del partner agregan los saldos de todas sus cuentas."""
        self._confirmed(700.0)
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.caw_balance, 700.0)
        self.assertEqual(self.partner.caw_withdrawal_count, 1)

    def test_cron_marks_installments_overdue(self):
        """El cron marca como vencidas las cuotas impagas con vencimiento pasado."""
        withdrawal = self._confirmed(100.0)
        withdrawal.installment_ids.date_due = "2026-01-02"
        self.env["caw.installment"]._cron_update_overdue()
        self.assertEqual(withdrawal.installment_ids.state, "overdue")
        self.assertTrue(withdrawal.is_overdue)
