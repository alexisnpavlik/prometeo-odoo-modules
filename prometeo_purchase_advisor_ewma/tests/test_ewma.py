# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.tests import tagged

from odoo.addons.prometeo_purchase_advisor.tests.common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestEwma(PurchaseAdvisorCommon):
    """Fase 6: un método nuevo entra sin tocar el módulo base."""

    def _estimate(self, product, model):
        series = self._build_series(model, product)
        return model.estimate(series)[product.id]

    def test_method_is_available_in_the_selection(self):
        methods = dict(self.env["prometeo.demand.model"]._selection_method())
        self.assertIn("ewma", methods)
        self.assertIn("weighted_ma", methods,
                      "El método del módulo base sigue estando")

    def test_dispatch_reaches_the_new_estimator(self):
        """El despacho por nombre del core encuentra el método del satélite."""
        self._sell_daily(self.product_a, 10, 91, 1)
        model = self._make_model(method="ewma", alpha=0.3)
        estimate = self._estimate(self.product_a, model)
        self.assertEqual(estimate.method_used, "ewma")

    def test_constant_demand(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        model = self._make_model(method="ewma", alpha=0.3)
        estimate = self._estimate(self.product_a, model)
        self.assertAlmostEqual(estimate.adu, 10.0, places=3)
        self.assertAlmostEqual(estimate.sigma, 0.0, places=3)

    def test_reacts_faster_than_the_weighted_average(self):
        """Ante un cambio de ritmo reciente, el EWMA se mueve más."""
        today = self._today()
        # 60 días vendiendo 2 y las últimas 3 semanas vendiendo 20.
        self._sell_daily(self.product_a, 2, 91, 22)
        self._sell_daily(self.product_a, 20, 22, 1)

        ewma = self._estimate(
            self.product_a, self._make_model(method="ewma", alpha=0.3))
        weighted = self._estimate(self.product_a, self._make_model())
        self.assertGreater(ewma.adu, weighted.adu)

    def test_alpha_controls_the_reaction(self):
        self._sell_daily(self.product_a, 2, 91, 22)
        self._sell_daily(self.product_a, 20, 22, 1)

        fast = self._estimate(
            self.product_a, self._make_model(method="ewma", alpha=0.5))
        slow = self._estimate(
            self.product_a, self._make_model(method="ewma", alpha=0.05))
        self.assertGreater(fast.adu, slow.adu)

    def test_degrades_when_there_is_not_enough_history(self):
        """No falla ni inventa: usa el promedio ponderado y lo deja asentado."""
        today = self._today()
        for offset in range(1, 4):
            self._make_move(self.product_a, 10, today - timedelta(days=offset))

        model = self._make_model(method="ewma", alpha=0.3)
        estimate = self._estimate(self.product_a, model)
        self.assertEqual(estimate.method_used, "weighted_ma")
        self.assertTrue(any("suavizado exponencial" in warning
                            for warning in estimate.warnings), estimate.warnings)

    def test_outlier_is_winsorized_by_the_core_helper(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self._make_move(self.product_a, 490, self._today() - timedelta(days=45))
        model = self._make_model(method="ewma", alpha=0.3)
        estimate = self._estimate(self.product_a, model)
        self.assertAlmostEqual(estimate.adu, 10.0, places=3)

    def test_explanation_names_the_method(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        model = self._make_model(method="ewma", alpha=0.3)
        estimate = self._estimate(self.product_a, model)
        self.assertIn("suavizado exponencial", estimate.explanation)
        self.assertIn("alpha", estimate.explanation)

    def test_ewma_model_needs_no_weight_config(self):
        """La validación de pesos del core solo aplica al promedio ponderado."""
        model = self._make_model(method="ewma", weight_config="14:0.9")
        self.assertEqual(model.method, "ewma")

    def test_suggestion_uses_the_assigned_model(self):
        """De punta a punta: una regla asigna EWMA y la línea lo registra."""
        self._sell_daily(self.product_a, 10, 91, 1)
        model = self._make_model(method="ewma", alpha=0.3)
        suggestion = self._make_suggestion(
            coverage_days=30, demand_model_id=model.id)
        suggestion.action_compute()

        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)
        self.assertEqual(line.method_used, "ewma")
        self.assertEqual(line.demand_model_id, model)
        self.assertAlmostEqual(line.adu, 10.0, places=2)
