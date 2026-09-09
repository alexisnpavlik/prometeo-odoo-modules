# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestAutomation(PurchaseAdvisorCommon):
    """Fase 5: explicabilidad, métricas de calidad y automatización."""

    # ------------------------------------------------------------------
    # Explicabilidad
    # ------------------------------------------------------------------
    def test_explanation_covers_demand_stock_and_lead_time(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)

        self.assertIn("unidades por día", line.explanation)
        self.assertIn("Quedan", line.explanation)
        self.assertIn("Plazo de entrega", line.explanation)
        self.assertIn("colchón", line.explanation)

    def test_warnings_reach_the_line(self):
        """Un producto nuevo tiene que decir por qué su estimación es endeble."""
        self._sell_daily(self.product_a, 10, 16, 1)
        suggestion = self._make_suggestion()
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)
        self.assertTrue(line.warnings)
        self.assertLessEqual(line.confidence, 0.2)

    def test_low_confidence_count_is_visible(self):
        self._sell_daily(self.product_a, 10, 16, 1)
        suggestion = self._make_suggestion()
        suggestion.action_compute()
        self.assertGreaterEqual(suggestion.low_confidence_count, 1)

    def test_compute_returns_a_notification(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        suggestion = self._make_suggestion()
        action = suggestion.action_compute()
        self.assertEqual(action["tag"], "display_notification")
        self.assertIn("recalculadas", action["params"]["message"])

    # ------------------------------------------------------------------
    # Métricas de calidad
    # ------------------------------------------------------------------
    def test_edit_rate_and_deviation(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_suggested": 10, "qty_final": 10},
            {"product_id": self.product_b.id, "supplier_id": self.supplier_a.id,
             "qty_suggested": 10, "qty_final": 30},
        ])
        self.assertAlmostEqual(suggestion.edit_rate, 0.5)
        self.assertAlmostEqual(suggestion.mean_deviation, 10.0)

    def test_manual_lines_do_not_count_as_edits(self):
        """Una línea que el usuario agregó no mide la calidad del modelo."""
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_suggested": 10, "qty_final": 10},
        ])
        self.env["prometeo.purchase.suggestion.line"].create({
            "suggestion_id": suggestion.id,
            "product_id": self.product_b.id,
            "supplier_id": self.supplier_a.id,
            "qty_final": 99, "is_manual": True,
        })
        self.assertAlmostEqual(suggestion.edit_rate, 0.0)

    # ------------------------------------------------------------------
    # Automatización
    # ------------------------------------------------------------------
    def test_cron_creates_a_suggestion_per_configured_warehouse(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self.warehouse.write({
            "auto_suggestion": True,
            "suggestion_user_id": self.env.user.id,
        })
        created = self.env["prometeo.purchase.suggestion"]._cron_generate_suggestions()

        self.assertEqual(len(created), 1)
        self.assertEqual(created.warehouse_id, self.warehouse)
        self.assertEqual(created.state, "computed")
        self.assertTrue(created.line_ids)

    def test_cron_skips_warehouses_without_the_flag(self):
        self.warehouse.auto_suggestion = False
        created = self.env["prometeo.purchase.suggestion"]._cron_generate_suggestions()
        self.assertFalse(created)

    def test_cron_leaves_a_review_activity(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self.warehouse.write({
            "auto_suggestion": True,
            "suggestion_user_id": self.env.user.id,
        })
        created = self.env["prometeo.purchase.suggestion"]._cron_generate_suggestions()
        self.assertTrue(created.activity_ids)
        self.assertEqual(created.activity_ids[0].user_id, self.env.user)

    def test_supplier_metrics_cron_writes_the_fields(self):
        self.supplier_a.action_refresh_purchase_metrics()
        self.assertTrue(self.supplier_a.metrics_date)

    def test_classification_cron_runs(self):
        self.env["product.product"]._cron_classify_products()
        self.assertTrue(self.product_a.abc_xyz_date)
