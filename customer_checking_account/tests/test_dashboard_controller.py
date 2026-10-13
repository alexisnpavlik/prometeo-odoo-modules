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

    def _confirmed(self, partner, qty, count=1, first_due="2027-01-01", frequency="monthly"):
        """Retiro confirmado del servicio de prueba en la compañía aislada."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": partner.id,
            "company_id": self.company.id,
            "date": "2026-01-01",
            "first_due_date": first_due,
            "installment_count": count,
            "frequency": frequency,
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

    def _charts(self):
        """Gráficos del dashboard sin filtros."""
        return self._controller()._cca_charts(
            self.env, start_date=None, end_date=None, company="all", partner="all"
        )

    def test_upcoming_collection_by_week(self):
        """Cobranza próxima: primero lo vencido y después 8 semanas desde hoy."""
        from datetime import timedelta
        from odoo import fields
        today = fields.Date.context_today(self.env.user)
        self._confirmed(self.partner, qty=2, first_due="2026-02-01")              # 100 vencido
        self._confirmed(self.partner, qty=4, count=2, frequency="weekly",
                        first_due=today + timedelta(days=1))                     # 100 + 100
        upcoming = self._charts()["upcoming"]
        self.assertEqual(len(upcoming["labels"]), 9)
        self.assertEqual(upcoming["labels"][0], "Vencido")
        self.assertEqual(upcoming["values"][0], 100.0)
        self.assertEqual(sum(upcoming["values"][1:3]), 200.0)

    def test_aging_buckets_overdue_debt(self):
        """Antigüedad: la deuda vencida hace más de 90 días cae en el último tramo."""
        self._confirmed(self.partner, qty=2, first_due="2026-02-01")
        aging = self._charts()["aging"]
        self.assertEqual(aging["labels"], ["1-30 días", "31-60 días", "61-90 días", "Más de 90 días"])
        self.assertEqual(aging["values"][3], 100.0)
        self.assertEqual(sum(aging["values"][:3]), 0.0)

    def test_collected_by_payment_method(self):
        """Cobrado por medio de pago, por mes."""
        self.env["cca.payment"].create({
            "partner_id": self.partner.id, "company_id": self.company.id,
            "amount": 300, "payment_method": "transfer",
        })
        self.env["cca.payment"].create({
            "partner_id": self.partner.id, "company_id": self.company.id,
            "amount": 50, "payment_method": "cash",
        })
        by_method = self._charts()["by_method"]
        totals = {serie["key"]: sum(serie["values"]) for serie in by_method["series"]}
        self.assertEqual(totals["transfer"], 300.0)
        self.assertEqual(totals["cash"], 50.0)
        self.assertEqual(len(by_method["labels"]), 1)
