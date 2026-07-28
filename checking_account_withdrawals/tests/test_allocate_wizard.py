# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawAllocateWizard(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)
        self.withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 600.0,
            })],
        })
        self.withdrawal._caw_generate_installments(
            count=3, first_days=30, period="months", cutoff_day=0
        )
        self.payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": 300.0,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        self.payment.state = "posted"

    def _wizard(self):
        """Abre el wizard de imputación manual precargado con las cuotas abiertas."""
        return self.env["caw.allocate.wizard"].with_context(
            active_model="caw.payment", active_id=self.payment.id
        ).create({"payment_id": self.payment.id})

    def test_wizard_preloads_open_installments(self):
        """El wizard lista las cuotas abiertas del partner."""
        wizard = self._wizard()
        self.assertEqual(len(wizard.line_ids), 3)
        self.assertEqual(wizard.amount_available, 300.0)

    def test_manual_allocation_targets_chosen_installments(self):
        """El Manager elige a qué cuotas aplicar, salteando el orden FIFO."""
        wizard = self._wizard()
        last_line = wizard.line_ids.sorted(lambda l: l.installment_id.sequence)[-1]
        wizard.line_ids.amount = 0.0
        last_line.amount = 200.0
        wizard.action_allocate()
        installments = self.withdrawal.installment_ids.sorted("sequence")
        self.assertEqual(installments[0].amount_allocated, 0.0)
        self.assertEqual(installments[2].amount_allocated, 200.0)

    def test_cannot_allocate_more_than_payment(self):
        """La suma de las líneas no puede superar el disponible del pago."""
        wizard = self._wizard()
        for line in wizard.line_ids:
            line.amount = 200.0
        with self.assertRaises(UserError):
            wizard.action_allocate()

    def test_cannot_allocate_more_than_residual(self):
        """Una línea no puede imputar más que el residual de su cuota."""
        wizard = self._wizard()
        wizard.line_ids.amount = 0.0
        first = wizard.line_ids.sorted(lambda l: l.installment_id.sequence)[0]
        first.amount = 250.0
        with self.assertRaises(UserError):
            wizard.action_allocate()
