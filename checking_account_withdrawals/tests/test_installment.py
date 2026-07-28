# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawInstallment(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True

    def _withdrawal(self, total=1000.0):
        """Retiro en borrador por el total indicado (una sola línea)."""
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-15",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })

    def test_single_installment_cash_mode(self):
        """Contado en cuenta: una sola cuota por el total, a X días."""
        withdrawal = self._withdrawal(1000.0)
        withdrawal._caw_generate_installments(count=1, first_days=30, period="months", cutoff_day=0)
        self.assertEqual(len(withdrawal.installment_ids), 1)
        installment = withdrawal.installment_ids
        self.assertEqual(installment.amount, 1000.0)
        self.assertEqual(str(installment.date_due), "2026-02-14")

    def test_fixed_installments_sum_equals_total(self):
        """Tres cuotas sobre 1000: la suma iguala exactamente el total."""
        withdrawal = self._withdrawal(1000.0)
        withdrawal._caw_generate_installments(count=3, first_days=30, period="months", cutoff_day=0)
        amounts = withdrawal.installment_ids.mapped("amount")
        self.assertEqual(len(amounts), 3)
        self.assertEqual(sum(amounts), 1000.0)

    def test_rounding_goes_to_last_installment(self):
        """El resto del redondeo se acumula en la última cuota, no en las primeras."""
        withdrawal = self._withdrawal(1000.0)
        withdrawal._caw_generate_installments(count=3, first_days=30, period="months", cutoff_day=0)
        amounts = withdrawal.installment_ids.sorted("sequence").mapped("amount")
        self.assertEqual(amounts[0], 333.33)
        self.assertEqual(amounts[1], 333.33)
        self.assertEqual(amounts[2], 333.34)

    def test_cutoff_day_shifts_due_dates(self):
        """Con día de corte 10, los vencimientos caen el 10 de cada mes."""
        withdrawal = self._withdrawal(900.0)
        withdrawal._caw_generate_installments(count=3, first_days=30, period="months", cutoff_day=10)
        dues = [str(d) for d in withdrawal.installment_ids.sorted("sequence").mapped("date_due")]
        self.assertEqual(dues, ["2026-02-10", "2026-03-10", "2026-04-10"])

    def test_confirm_generates_installments_and_moves_state(self):
        """Confirmar genera las cuotas con los defaults de la compañía y pasa a pendiente."""
        self.company.caw_installment_count = 2
        self.company.caw_installment_days = 15
        self.company.caw_cutoff_day = 0
        withdrawal = self._withdrawal(500.0)
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(len(withdrawal.installment_ids), 2)
        self.assertEqual(sum(withdrawal.installment_ids.mapped("amount")), 500.0)

    def test_confirm_rejects_empty_withdrawal(self):
        """No se confirma un retiro sin líneas."""
        withdrawal = self.env["caw.withdrawal"].create({"partner_id": self.partner.id})
        with self.assertRaises(UserError):
            withdrawal.action_confirm()

    def test_confirm_rejects_zero_total(self):
        """No se confirma un retiro con total menor o igual a cero."""
        withdrawal = self._withdrawal(0.0)
        with self.assertRaises(UserError):
            withdrawal.action_confirm()

    def test_manual_installments_must_match_total(self):
        """La suma de cuotas cargadas a mano debe igualar exactamente el total."""
        withdrawal = self._withdrawal(1000.0)
        with self.assertRaises(ValidationError):
            self.env["caw.installment"].create({
                "withdrawal_id": withdrawal.id,
                "sequence": 1,
                "date_due": "2026-02-15",
                "amount": 400.0,
            })
            withdrawal.installment_ids._check_total_matches_withdrawal()

    def test_due_date_cannot_precede_withdrawal_date(self):
        """El vencimiento de una cuota no puede ser anterior a la fecha del retiro."""
        withdrawal = self._withdrawal(1000.0)
        with self.assertRaises(ValidationError):
            self.env["caw.installment"].create({
                "withdrawal_id": withdrawal.id,
                "sequence": 1,
                "date_due": "2026-01-01",
                "amount": 1000.0,
            })

    def test_due_date_never_precedes_withdrawal_date_with_cutoff(self):
        """Un día de corte anterior al día del retiro no genera vencimientos pasados.

        Antes del fix, first_days=5 + cutoff_day=1 sobre un retiro del 2026-01-05
        producía due=2026-01-01, anterior a la fecha del retiro.
        """
        withdrawal = self._withdrawal(1000.0)
        withdrawal.date = "2026-01-05"
        withdrawal._caw_generate_installments(count=1, first_days=5, period="days", cutoff_day=1)
        for installment in withdrawal.installment_ids:
            self.assertGreaterEqual(installment.date_due, withdrawal.date)

    def test_company_cutoff_day_out_of_range_is_rejected(self):
        """El día de corte de la compañía debe estar entre 0 y 28."""
        with self.assertRaises(ValidationError):
            self.company.caw_cutoff_day = 29

    def test_lines_are_locked_after_confirm(self):
        """Un retiro confirmado no admite edición de líneas."""
        withdrawal = self._withdrawal(500.0)
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.write({"line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 50.0,
            })]})
