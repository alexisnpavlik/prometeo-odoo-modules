# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawStatement(CawCommon):

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
                "price_unit": 500.0,
            })],
        })
        self.withdrawal._caw_generate_installments(
            count=2, first_days=30, period="months", cutoff_day=0
        )

    def test_statement_data_respects_cutoff_date(self):
        """El resumen solo incluye movimientos hasta la fecha de corte."""
        late = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-12-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 999.0,
            })],
        })
        late._caw_generate_installments(count=1, first_days=30, period="months", cutoff_day=0)
        wizard = self.env["caw.statement.wizard"].create({
            "account_id": self.account.id,
            "date_to": "2026-06-30",
        })
        data = wizard._caw_statement_data()
        self.assertIn(self.withdrawal, data["withdrawals"])
        self.assertNotIn(late, data["withdrawals"])

    def test_statement_includes_payments_and_balance(self):
        """El resumen trae los pagos imputados y el saldo final a la fecha."""
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": 250.0,
            "date": "2026-03-01",
            "payment_method": "cash",
        })
        payment.action_post()
        wizard = self.env["caw.statement.wizard"].create({
            "account_id": self.account.id,
            "date_to": "2026-06-30",
        })
        data = wizard._caw_statement_data()
        self.assertIn(payment, data["payments"])
        self.assertEqual(data["balance"], 250.0)

    def test_report_renders_without_error(self):
        """El PDF se renderiza sin excepciones."""
        wizard = self.env["caw.statement.wizard"].create({
            "account_id": self.account.id,
            "date_to": "2026-06-30",
        })
        report = self.env["ir.actions.report"]._render_qweb_html(
            "checking_account_withdrawals.action_report_caw_statement", wizard.ids
        )
        self.assertTrue(report[0])
