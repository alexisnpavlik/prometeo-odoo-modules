# -*- coding: utf-8 -*-
from datetime import date

from .common import CcaCommon


class TestStatement(CcaCommon):

    def test_statement_data_and_pdf(self):
        """El estado de cuenta suma retiros y pagos a la fecha y renderiza el PDF."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": 4})],
        })
        withdrawal.action_confirm()
        self.env["cca.payment"].create({
            "account_id": withdrawal.account_id.id, "amount": 50, "date": date(2026, 2, 1),
        })
        wizard = self.env["cca.statement.wizard"].create({
            "account_id": withdrawal.account_id.id, "date_to": date(2027, 3, 1),
        })
        data = wizard._cca_statement_data()
        self.assertEqual(data["total_withdrawn"], 200.0)
        self.assertEqual(data["total_paid"], 50.0)
        self.assertEqual(data["balance"], 150.0)
        pdf, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "customer_checking_account.action_report_cca_statement", wizard.ids
        )
        self.assertIn(b"Cliente CCA Test", pdf)
