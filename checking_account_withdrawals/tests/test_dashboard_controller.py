# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawDashboard(CawCommon):
    """Testea la lógica del controller sin pasar por HTTP."""

    def setUp(self):
        super().setUp()
        # `base.main_company` está archivada en la DB `calidad` (dato preexistente, ajeno a
        # este módulo). Al estar inactiva, el ORM la excluye de `env.companies` (Many2many
        # con active_test), aunque siga siendo la `company_id` de los fixtures compartidos
        # en CawCommon. Como el controller scopea sus queries a `env.companies.ids`, la
        # reactivamos solo dentro de esta transacción de test (se revierte con el rollback
        # de TransactionCase) para poder ejercitar ese scoping tal como lo hará en producción.
        self.company.sudo().active = True
        self.partner.caw_enabled = True
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 1000.0,
            })],
        })
        withdrawal._caw_generate_installments(
            count=2, first_days=30, period="months", cutoff_day=0
        )
        self.withdrawal = withdrawal

    def _controller(self):
        """Instancia el controller para llamar sus helpers directamente."""
        from odoo.addons.checking_account_withdrawals.controllers.dashboard_controller import (
            CawDashboardController,
        )
        return CawDashboardController()

    def test_kpis_reflect_open_balance(self):
        """Los KPIs reportan el saldo de cartera y la cantidad de retiros."""
        kpis = self._controller()._caw_kpis(
            self.env, start_date=None, end_date=None, company="all"
        )
        self.assertEqual(kpis["total_balance"], 1000.0)
        self.assertEqual(kpis["withdrawal_count"], 1)
        self.assertEqual(kpis["credit_balance"], 0.0)

    def test_installment_status_chart_counts_states(self):
        """El gráfico de estados agrupa las cuotas por estado."""
        charts = self._controller()._caw_charts(
            self.env, start_date=None, end_date=None, company="all"
        )
        status = charts["installment_status"]
        self.assertEqual(sum(status["values"]), 2)

    def test_top_partners_lists_debtors(self):
        """El top de partners lista a los deudores por saldo."""
        charts = self._controller()._caw_charts(
            self.env, start_date=None, end_date=None, company="all"
        )
        self.assertIn(self.partner.display_name, charts["top_partners"]["labels"])

    def test_access_is_denied_without_group(self):
        """Un usuario sin el grupo Manager no accede al dashboard."""
        user = self.env["res.users"].create({
            "name": "Sin permisos CC",
            "login": "caw_no_access_test",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self._controller()._check_access(self.env(user=user))
