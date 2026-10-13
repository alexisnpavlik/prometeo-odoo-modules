# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CcaCommon


@tagged("post_install", "-at_install")
class TestCcaDashboard(CcaCommon):
    """Testea la lógica del controller sin pasar por HTTP."""

    def setUp(self):
        super().setUp()
        # Compañía propia: el controller suma toda la cartera de env.companies y la base
        # puede traer retiros de otras corridas.
        self.company = self.env["res.company"].create({"name": "CCA Dashboard Test Co"})
        self.env.user.company_ids = [(4, self.company.id)]
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=[self.company.id]))
        self.account = self.env["cca.account"]._get_or_create(self.partner, self.company)
        self.withdrawal = self._confirmed(self.partner, qty=20, count=2)  # 20 x 50 = 1000

    def _confirmed(self, partner, qty, count=1):
        """Retiro confirmado del servicio de prueba en la compañía aislada."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": partner.id,
            "company_id": self.company.id,
            "date": "2026-01-01",
            "first_due_date": "2027-01-01",
            "installment_count": count,
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": qty})],
        })
        withdrawal.action_confirm()
        return withdrawal

    def _controller(self):
        """Instancia el controller para llamar sus helpers directamente."""
        from odoo.addons.customer_checking_account.controllers.dashboard_controller import (
            CcaDashboardController,
        )
        return CcaDashboardController()

    def test_kpis_reflect_open_balance(self):
        """Los KPIs reportan el saldo de cartera y la cantidad de retiros."""
        kpis = self._controller()._cca_kpis(
            self.env, start_date=None, end_date=None, company="all", partner="all"
        )
        self.assertEqual(kpis["total_balance"], 1000.0)
        self.assertEqual(kpis["withdrawal_count"], 1)
        self.assertEqual(kpis["credit_balance"], 0.0)

    def test_installment_status_chart_counts_states(self):
        """El gráfico de estados agrupa las cuotas por estado."""
        charts = self._controller()._cca_charts(
            self.env, start_date=None, end_date=None, company="all", partner="all"
        )
        status = charts["installment_status"]
        self.assertEqual(sum(status["values"]), 2)

    def test_top_partners_lists_debtors(self):
        """El top de partners lista a los deudores por saldo."""
        charts = self._controller()._cca_charts(
            self.env, start_date=None, end_date=None, company="all", partner="all"
        )
        self.assertIn(self.partner.display_name, charts["top_partners"]["labels"])

    def test_partner_filter_narrows_kpis_to_one_contact(self):
        """El filtro de contacto acota los KPIs a un solo partner, ignorando al resto."""
        other = self.env["res.partner"].create({"name": "Otro Dashboard Test", "vat": "20999888"})
        self._confirmed(other, qty=10)
        kpis = self._controller()._cca_kpis(
            self.env, start_date=None, end_date=None, company="all", partner=str(self.partner.id)
        )
        self.assertEqual(kpis["total_balance"], 1000.0)
        self.assertEqual(kpis["withdrawal_count"], 1)

    def test_filters_lists_partners_with_account(self):
        """_cca_partners expone los contactos con cuenta corriente, para el filtro."""
        names = [p["name"] for p in self._controller()._cca_partners(self.env)]
        self.assertIn(self.partner.display_name, names)

    def test_access_is_denied_without_group(self):
        """Un usuario sin el grupo de cuenta corriente no accede al dashboard."""
        user = self.env["res.users"].create({
            "name": "Sin permisos CC",
            "login": "cca_no_access_test",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self._controller()._check_access(self.env(user=user))
