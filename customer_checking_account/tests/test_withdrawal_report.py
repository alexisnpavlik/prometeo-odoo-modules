# -*- coding: utf-8 -*-
from datetime import date

from .common import CcaCommon


class TestWithdrawalReport(CcaCommon):

    def test_withdrawal_receipt_renders(self):
        """El comprobante del retiro muestra cliente, productos, entrega y cuotas."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "installment_count": 2,
            "down_payment": 100.0,
            "surcharge_percent": 10.0,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": 6})],
        })
        withdrawal.action_confirm()
        action = withdrawal.action_print()
        self.assertEqual(action["report_name"], "customer_checking_account.report_cca_withdrawal")
        html, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "customer_checking_account.action_report_cca_withdrawal", withdrawal.ids
        )
        html = html.decode()
        for text in ("Cliente CCA Test", "30111222", withdrawal.name, "Servicio CCA Test",
                     "Entrega", "1/2", "2/2", "Firma"):
            self.assertIn(text, html)
