from .common import BranchTransferCommon


class TestReport(BranchTransferCommon):
    """El remito se imprime con una sola sucursal seleccionada."""

    def test_print_with_only_own_company_selected(self):
        self.set_stock(self.product, self.company_a, 50.0)
        transfer = self.make_transfer(self.user_a)
        transfer.with_user(self.user_a).action_send()
        for user, company in ((self.user_b, self.company_b), (self.user_a, self.company_a)):
            self.env.invalidate_all()
            report = self.env["ir.actions.report"].with_user(user).with_context(allowed_company_ids=[company.id])
            html, _type = report._render_qweb_html("stock_branch_transfer.report_branch_transfer", transfer.ids)
            self.assertIn(transfer.name, html.decode())
            self.assertIn(self.company_a.name, html.decode())
            self.assertIn(self.company_b.name, html.decode())

    def test_print_draft(self):
        self.set_stock(self.product, self.company_a, 50.0)
        transfer = self.make_transfer(self.user_a)
        report = self.env["ir.actions.report"].with_user(self.user_a).with_context(allowed_company_ids=[self.company_a.id])
        html, _type = report._render_qweb_html("stock_branch_transfer.report_branch_transfer", transfer.ids)
        self.assertEqual(transfer.state, "draft")
        self.assertIn("TODAVÍA NO ENVIADO", html.decode())
        self.assertIn(self.product.display_name, html.decode())
