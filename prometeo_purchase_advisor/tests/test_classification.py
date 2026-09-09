# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo import Command

from .common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestClassification(PurchaseAdvisorCommon):
    """Fase 4: clasificación ABC/XYZ, exclusiones y filtro de prioridad."""

    # ------------------------------------------------------------------
    # ABC
    # ------------------------------------------------------------------
    def test_abc_ranks_by_consumption_value_not_units(self):
        """Vender 500 medias no es lo mismo que vender 20 camperas."""
        company, warehouse = self._isolated_company("ABC")
        medias = self._make_product("Medias", self.supplier_a, price=10.0)
        camperas = self._make_product("Camperas", self.supplier_a, price=1000.0)
        medias.with_company(company).standard_price = 1.0
        camperas.with_company(company).standard_price = 500.0

        # 500 unidades a 1 de costo contra 20 unidades a 500.
        self._sell_daily(medias, 10, 51, 1, warehouse=warehouse)
        self._sell_daily(camperas, 1, 21, 1, warehouse=warehouse)

        self.env["product.product"]._classify_for_company(company)
        self.assertEqual(camperas.abc_class, "a")
        self.assertNotEqual(medias.abc_class, "a")

    def test_products_without_sales_fall_to_c(self):
        self.env["product.product"]._classify_for_company(self.company)
        self.assertEqual(self.product_a.abc_class, "c")
        self.assertTrue(self.product_a.abc_xyz_date)

    # ------------------------------------------------------------------
    # XYZ
    # ------------------------------------------------------------------
    def test_steady_demand_is_class_x(self):
        self._sell_daily(self.product_a, 10, 181, 1)
        self.product_a.standard_price = 5.0
        self.env["product.product"]._classify_for_company(self.company)
        self.assertEqual(self.product_a.xyz_class, "x")

    def test_erratic_demand_is_class_z(self):
        """Todo el volumen concentrado en pocos días: variabilidad alta."""
        today = self._today()
        from datetime import timedelta
        for offset in (10, 60, 120):
            self._make_move(self.product_a, 500, today - timedelta(days=offset))
        self.product_a.standard_price = 5.0
        self.env["product.product"]._classify_for_company(self.company)
        self.assertEqual(self.product_a.xyz_class, "z")

    def test_coefficient_of_variation(self):
        Product = self.env["product.product"]
        # 180 días, 1800 unidades, 10 por día exactos: sin variación.
        cv = Product._coefficient_of_variation(total=1800.0, sumsq=18000.0, days=180)
        self.assertAlmostEqual(cv, 0.0, places=6)
        self.assertIsNone(Product._coefficient_of_variation(0.0, 0.0, 180))

    # ------------------------------------------------------------------
    # Filtro de prioridad
    # ------------------------------------------------------------------
    def test_class_c_only_appears_when_about_to_break(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self.product_a.abc_class = "c"
        suggestion = self._make_suggestion(coverage_days=30)

        # Cobertura de sobra: el producto C no molesta la lista.
        self._set_stock(self.product_a, 1000)
        suggestion.action_compute()
        self.assertFalse(suggestion.line_ids.filtered(
            lambda line: line.product_id == self.product_a))

    def test_class_c_appears_when_coverage_is_short(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self.product_a.abc_class = "c"
        self._set_stock(self.product_a, 20)      # 2 días contra 10 de plazo
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        self.assertTrue(suggestion.line_ids.filtered(
            lambda line: line.product_id == self.product_a))

    def test_class_c_can_be_forced_in(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self.product_a.abc_class = "c"
        self._set_stock(self.product_a, 1000)
        self.company.suggestion_always_include_c = True
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        # Entra al cálculo aunque después la cantidad dé cero y no se cree línea.
        self.assertTrue(suggestion._should_include(
            self.product_a, self._dummy_estimate(), coverage=100.0,
            lead_time=10.0, on_hand=1000.0))

    def _dummy_estimate(self):
        from odoo.addons.prometeo_purchase_advisor.models.datatypes import Estimate
        return Estimate(adu=10.0, sigma=1.0, confidence=0.9,
                        method_used="weighted_ma")

    def test_dead_stock_is_excluded(self):
        """Sin ventas en la ventana y con mercadería en el depósito: no se repone."""
        self._set_stock(self.product_a, 50)
        suggestion = self._make_suggestion()
        from odoo.addons.prometeo_purchase_advisor.models.datatypes import Estimate
        self.assertFalse(suggestion._should_include(
            self.product_a, Estimate(adu=0.0), coverage=9999.0,
            lead_time=10.0, on_hand=50.0))

    # ------------------------------------------------------------------
    # Exclusiones
    # ------------------------------------------------------------------
    def test_excluded_product_never_enters(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self.product_a.product_tmpl_id.exclude_from_suggestion = True
        suggestion = self._make_suggestion()
        self.assertNotIn(self.product_a, suggestion._candidate_products())

    def test_product_without_supplier_is_a_candidate(self):
        suggestion = self._make_suggestion()
        self.assertIn(self.product_no_seller, suggestion._candidate_products())

    def test_category_selection_supports_multiple_and_descendants(self):
        """El filtro combina categorías y puede limitarse a las categorías exactas."""
        categories = self.env['product.category']
        parent = categories.create({'name': 'Muebles seleccionados'})
        child = categories.create({'name': 'Sillas seleccionadas', 'parent_id': parent.id})
        other = categories.create({'name': 'Decoración seleccionada'})
        self.product_a.categ_id = parent
        self.product_b.categ_id = child
        self.product_c.categ_id = other
        suggestion = self._make_suggestion(category_ids=[Command.set(parent.ids)])
        self.assertIn(self.product_a, suggestion._candidate_products())
        self.assertIn(self.product_b, suggestion._candidate_products())
        self.assertNotIn(self.product_c, suggestion._candidate_products())
        suggestion.write({'include_subcategories': False,
                          'category_ids': [Command.set((parent | other).ids)]})
        self.assertIn(self.product_a, suggestion._candidate_products())
        self.assertNotIn(self.product_b, suggestion._candidate_products())
        self.assertIn(self.product_c, suggestion._candidate_products())
        suggestion.category_ids = [Command.clear()]
        self.assertIn(self.product_b, suggestion._candidate_products())

    def test_non_storable_product_is_not_a_candidate(self):
        service = self.env["product.product"].create({
            "name": "Servicio", "type": "service", "purchase_ok": True,
        })
        self.env["product.supplierinfo"].create({
            "partner_id": self.supplier_a.id,
            "product_tmpl_id": service.product_tmpl_id.id, "price": 10.0,
        })
        suggestion = self._make_suggestion()
        self.assertNotIn(service, suggestion._candidate_products())

    def test_archived_product_is_not_a_candidate(self):
        self.product_a.action_archive()
        suggestion = self._make_suggestion()
        self.assertNotIn(self.product_a, suggestion._candidate_products())

    # ------------------------------------------------------------------
    # Orden
    # ------------------------------------------------------------------
    def test_lines_are_ordered_by_urgency(self):
        """Lo que está por quebrar aparece primero."""
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_final": 5, "coverage_days_current": 40.0, "adu": 2.0},
            {"product_id": self.product_b.id, "supplier_id": self.supplier_a.id,
             "qty_final": 5, "coverage_days_current": 3.0, "adu": 8.0},
        ])
        ordered = self.env["prometeo.purchase.suggestion.line"].search(
            [("suggestion_id", "=", suggestion.id)])
        self.assertEqual(ordered[0].product_id, self.product_b)
