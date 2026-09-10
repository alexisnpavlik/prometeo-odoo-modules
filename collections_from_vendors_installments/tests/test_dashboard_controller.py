# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..controllers.dashboard_controller import CviDashboardController
from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviDashboardController(CviCommon):
    """HU-32. Se ejercita el controlador directamente pasándole el env: montar una
    request HTTP en TransactionCase no aporta nada sobre lo que se quiere fijar, que
    es el cálculo de los indicadores."""

    def setUp(self):
        super().setUp()
        self.controller = CviDashboardController()
        self.company.cvi_overdue_days = 0
        self.card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    def _kpis(self, start=None, end=None):
        return self.controller._cvi_kpis(self.env, start, end, "all")

    def _charts(self, start=None, end=None):
        return self.controller._cvi_charts(self.env, start, end, "all")

    def _multi_company_env(self, company):
        """Habilita ``company`` además de la principal para simular el selector web."""
        self.env.user.company_ids = [(4, company.id)]
        self.env.invalidate_all()
        return self.env(context={
            **self.env.context,
            "allowed_company_ids": [self.company.id, company.id],
        })

    def _other_company_card(self, company):
        """Crea una tarjeta mínima en otra empresa para las consultas del tablero."""
        customer = self.env["cvi.customer"].create({
            "name": "Cliente Otra Empresa",
            "dni": "30999999",
            "company_id": company.id,
        })
        vendor = self.env["res.users"].create({
            "name": "Vendedor Otra Empresa",
            "login": "cvi_vendor_other_company",
            "company_id": company.id,
            "company_ids": [(6, 0, [company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        card = self.env["cvi.card"].create({
            "company_id": company.id,
            "customer_id": customer.id,
            "vendor_id": vendor.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        card.state = "active"
        return card, vendor

    # --- permisos ---

    def test_a_collector_cannot_open_the_dashboard(self):
        """El tablero es del administrador (HU-32)."""
        with self.assertRaises(AccessError):
            self.controller._check_access(self.env(user=self.collector_user))

    def test_a_manager_can_open_the_dashboard(self):
        manager = self.env["res.users"].create({
            "name": "Admin Tablero",
            "login": "cvi_manager_dashboard",
            "email": "dashboard@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_manager").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.controller._check_access(self.env(user=manager))

    # --- KPIs ---

    def test_sold_counts_the_confirmed_card(self):
        kpis = self._kpis()
        self.assertEqual(kpis["card_count"], 1)
        self.assertEqual(kpis["sold"], self.card.amount_total)

    def test_draft_cards_are_not_business(self):
        """Una venta sin confirmar no es negocio: no entra en los indicadores."""
        self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        self.assertEqual(self._kpis()["card_count"], 1)

    def test_period_filter_excludes_older_sales(self):
        self.assertEqual(self._kpis(start="2099-01-01")["card_count"], 0)

    def test_collected_excludes_the_vendor_commission(self):
        """La comisión no es cobranza de la empresa: es del vendedor por RN-01."""
        self.card.action_charge_first_installment()
        self.assertEqual(self._kpis()["collected"], 0.0)

    def test_collected_counts_a_real_payment(self):
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 5000.0, "date": "2020-03-10",
        })
        payment.action_post()
        self.assertEqual(self._kpis()["collected"], 5000.0)

    def test_collected_is_measured_by_payment_date(self):
        """Un cobro de hoy sobre una venta vieja tiene que aparecer en el período de hoy.

        Si se midiera por fecha de venta, la cobranza reciente de carteras antiguas no
        aparecería en ningún período.
        """
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 5000.0, "date": "2024-06-10",
        })
        payment.action_post()
        self.assertEqual(self._kpis(start="2024-01-01", end="2024-12-31")["collected"], 5000.0)

    def test_overdue_ignores_the_commission_installment(self):
        kpis = self._kpis()
        overdue = self.card.installment_ids.filtered(
            lambda i: i.state == "overdue" and not i.is_commission
        )
        self.assertEqual(kpis["overdue_installments"], len(overdue))

    def test_overdue_rate_is_a_percentage(self):
        rate = self._kpis()["overdue_rate"]
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 100.0)

    def test_recovery_counters(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.assertEqual(self._kpis()["to_recover_count"], 1)
        self.card.action_register_recovery()
        self.assertEqual(self._kpis()["recovered_count"], 1)

    # --- gráficos ---

    def test_sales_by_vendor_series(self):
        charts = self._charts()
        self.assertIn(self.vendor_user.display_name, charts["sales_by_vendor"]["vendors"])

    def test_portfolio_by_collector_has_the_three_series(self):
        charts = self._charts()
        portfolio = charts["portfolio_by_collector"]
        self.assertIn(self.collector_user.display_name, portfolio["labels"])
        self.assertEqual(
            len(portfolio["residual"]), len(portfolio["overdue"])
        )
        self.assertEqual(
            len(portfolio["residual"]), len(portfolio["collected"])
        )

    def test_aging_has_the_four_buckets(self):
        aging = self._charts()["aging"]
        self.assertEqual(len(aging["labels"]), 4)
        self.assertEqual(len(aging["values"]), 4)

    def test_aging_puts_an_old_debt_in_the_last_bucket(self):
        """Una venta de 2020 tiene toda su deuda a más de 90 días."""
        aging = self._charts()["aging"]
        self.assertGreater(aging["values"][3], 0.0)
        self.assertEqual(aging["values"][0], 0.0)

    def test_settlement_differences_series(self):
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 5000.0,
            "date": "2020-03-10", "user_id": self.collector_user.id,
        })
        payment.action_post()
        settlement = self.env["cvi.settlement"].create({
            "collector_id": self.collector_user.id,
            "date_to": "2020-03-31",
            "frequency": "monthly",
        })
        settlement.amount_delivered = 4000.0
        settlement.action_submit()
        diffs = self.controller._cvi_charts(
            self.env, "2020-01-01", "2020-12-31", "all"
        )["settlement_differences"]
        self.assertIn(self.collector_user.display_name, diffs["labels"])

    def test_vendor_stock_series_lists_the_vendor_location(self):
        stock = self._charts()["vendor_stock"]
        self.assertIn(self.vendor_location.display_name, stock["labels"])

    def test_selected_company_filters_collected_by_collector(self):
        """Los cobros de otra empresa no inflan la cartera del cobrador seleccionado."""
        other_company = self.env["res.company"].create({"name": "Empresa Dos"})
        other_env = self._multi_company_env(other_company)
        other_card, _vendor = self._other_company_card(other_company)
        self.env["cvi.payment"].create({
            "card_id": self.card.id,
            "amount": 1000.0,
            "date": "2020-03-10",
            "user_id": self.collector_user.id,
            "state": "posted",
        })
        self.env["cvi.payment"].create({
            "card_id": other_card.id,
            "amount": 7000.0,
            "date": "2020-03-10",
            "user_id": self.collector_user.id,
            "state": "posted",
        })

        portfolio = self.controller._cvi_charts(
            other_env, None, None, str(other_company.id)
        )["portfolio_by_collector"]

        position = portfolio["labels"].index(self.collector_user.display_name)
        self.assertEqual(portfolio["collected"][position], 7000.0)

    def test_selected_company_filters_vendor_stock(self):
        """El stock de otra empresa no aparece al elegir una empresa concreta."""
        other_company = self.env["res.company"].create({"name": "Empresa Dos"})
        other_env = self._multi_company_env(other_company)
        parent = self.env["stock.location"].sudo().create({
            "name": "Vendedores Empresa Dos",
            "usage": "view",
            "company_id": other_company.id,
        })
        other_location = self.env["stock.location"].sudo().create({
            "name": "Vendedor Empresa Dos",
            "usage": "internal",
            "location_id": parent.id,
            "company_id": other_company.id,
            "cvi_is_vendor_location": True,
        })
        self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": other_location.id,
            "inventory_quantity": 17,
        }).action_apply_inventory()

        stock = self.controller._cvi_charts(
            other_env, None, None, str(other_company.id)
        )["vendor_stock"]

        self.assertEqual(stock["labels"], [other_location.display_name])
        self.assertEqual(stock["values"], [17.0])

    # --- mapa ---

    def test_map_only_includes_sales_with_coordinates(self):
        self.assertEqual(self.controller._cvi_map_points(self.env, None, None, "all"), [])
        self.card.write({"cvi_latitude": -27.45, "cvi_longitude": -58.98})
        points = self.controller._cvi_map_points(self.env, None, None, "all")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["name"], self.card.name)

    # --- listados ---

    def test_records_domain_for_cards_excludes_drafts(self):
        domain, model, date_field = self.controller._cvi_records_domain(
            self.env, "cards", None, None, "all", None
        )
        self.assertEqual(model._name, "cvi.card")
        self.assertEqual(date_field, "date_sale")
        self.assertIn(("state", "not in", ("draft", "cancel")), domain)

    def test_records_domain_for_installments(self):
        domain, model, date_field = self.controller._cvi_records_domain(
            self.env, "installments", None, None, "all", None
        )
        self.assertEqual(model._name, "cvi.installment")
        self.assertEqual(date_field, "date_due")

    def test_records_domain_searches_customers_by_name_and_dni(self):
        """El Many2one conserva ambas claves de búsqueda declaradas por cvi.customer."""
        for search in (self.customer.name, self.customer.dni):
            domain, model, _date_field = self.controller._cvi_records_domain(
                self.env, "cards", None, None, "all", search
            )
            self.assertIn(self.card, model.search(domain))

    def test_invalid_company_is_a_functional_error(self):
        for company in (
            "not-a-company", "99999999", "1.0", " 1", "+1", "-1",
            0, -1, True, float(self.company.id) + 0.9,
            float("inf"), float("nan"),
        ):
            with self.subTest(company=company), self.assertRaises(UserError):
                self.controller._cvi_parse_company(self.env, company)

    def test_invalid_pagination_is_a_functional_error(self):
        for page, per_page in (
            ("not-a-page", 15), (1, "not-a-page"), (0, 15),
            (1.9, 15), (1, 15.9), (True, 15), (1, True),
        ):
            with self.subTest(page=page, per_page=per_page), self.assertRaises(UserError):
                self.controller._cvi_parse_pagination(page, per_page)

    def test_invalid_records_model_is_a_functional_error(self):
        with self.assertRaises(UserError):
            self.controller._cvi_records_domain(
                self.env, "not-a-model", None, None, "all", None
            )

    def test_serialization_of_a_card(self):
        data = self.controller._cvi_serialize(self.card, "cards")
        self.assertEqual(data["name"], self.card.name)
        self.assertEqual(data["vendor"], self.vendor_user.display_name)
        self.assertEqual(data["state"], "En cobranza")
