# -*- coding: utf-8 -*-
import math
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from .common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestQuantity(PurchaseAdvisorCommon):
    """Fase 3: lead time medido, stock de seguridad y restricciones del proveedor."""

    # ------------------------------------------------------------------
    # Lead time
    # ------------------------------------------------------------------
    def _receive_po(self, supplier, product, qty, approved_days_ago, received_days_ago):
        """Orden de compra confirmada y recibida, con fechas retroactivas."""
        po = self.env["purchase.order"].create({
            "partner_id": supplier.id,
            "company_id": self.company.id,
            "picking_type_id": self.warehouse.in_type_id.id,
            "order_line": [Command.create({
                "product_id": product.id,
                "product_qty": qty,
                "product_uom": product.uom_po_id.id,
                "price_unit": 10.0,
                "name": product.name,
                "date_planned": fields.Datetime.now(),
            })],
        })
        po.button_confirm()
        picking = po.picking_ids
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.button_validate()
        now = fields.Datetime.now()
        po.write({"date_approve": now - timedelta(days=approved_days_ago)})
        picking.write({"date_done": now - timedelta(days=received_days_ago)})
        return po

    def test_lead_time_is_measured_from_real_orders(self):
        for _index in range(3):
            self._receive_po(self.supplier_a, self.product_a, 5, 40, 28)
        measured = self.supplier_a._measure_lead_times()
        days, sample = measured[self.supplier_a.id]

        self.assertEqual(sample, 3)
        self.assertAlmostEqual(days, 12.0, places=1)

    def test_small_sample_falls_back_to_configured_delay(self):
        """Con una sola orden el promedio no significa nada: manda el configurado."""
        self._receive_po(self.supplier_a, self.product_a, 5, 40, 28)
        seller = self.product_a.seller_ids[0]
        lead_times = self.supplier_a._lead_time_for_suggestion(
            {self.supplier_a.id: seller})
        self.assertAlmostEqual(lead_times[self.supplier_a.id], 10.0,
                               msg="delay del supplierinfo")

    def test_without_history_or_config_uses_one_week(self):
        seller = self.product_a.seller_ids[0]
        seller.delay = 0
        lead_times = self.supplier_a._lead_time_for_suggestion(
            {self.supplier_a.id: seller})
        self.assertAlmostEqual(lead_times[self.supplier_a.id], 7.0)

    def test_fill_rate_is_measured(self):
        self._receive_po(self.supplier_a, self.product_a, 10, 30, 20)
        rates = self.supplier_a._measure_fill_rates()
        self.assertAlmostEqual(rates[self.supplier_a.id], 1.0, places=2)

    # ------------------------------------------------------------------
    # Stock de seguridad
    # ------------------------------------------------------------------
    def test_safety_stock_formula(self):
        model = self._make_model(service_level=0.95)
        safety = model._safety_stock(sigma=4.0, lead_time_days=9.0, adu=10.0)
        self.assertAlmostEqual(safety, 1.65 * 4.0 * 3.0, places=2)

    def test_safety_stock_floor_when_sigma_is_zero(self):
        """Desvío cero casi siempre es falta de datos, no demanda estable."""
        model = self._make_model()
        self.assertAlmostEqual(
            model._safety_stock(sigma=0.0, lead_time_days=9.0, adu=10.0), 5.0)

    # ------------------------------------------------------------------
    # Fórmula de cantidad
    # ------------------------------------------------------------------
    def _estimate_stub(self, adu=10.0, sigma=0.0):
        from odoo.addons.prometeo_purchase_advisor.models.datatypes import Estimate
        return Estimate(adu=adu, sigma=sigma, confidence=0.9,
                        method_used="weighted_ma")

    def test_target_quantity_discounts_stock_and_incoming(self):
        suggestion = self._make_suggestion(coverage_days=30)
        qty = suggestion._target_quantity(
            self._estimate_stub(adu=10.0), lead_time_days=10.0,
            safety_stock=5.0, on_hand=100.0, incoming=50.0, outgoing=0.0)
        self.assertAlmostEqual(qty, 10 * 40 + 5 - 100 - 50)

    def test_target_quantity_adds_committed_outgoing(self):
        """Lo ya vendido y sin despachar no es stock disponible."""
        suggestion = self._make_suggestion(coverage_days=30)
        qty = suggestion._target_quantity(
            self._estimate_stub(adu=10.0), lead_time_days=10.0,
            safety_stock=5.0, on_hand=100.0, incoming=0.0, outgoing=20.0)
        self.assertAlmostEqual(qty, 10 * 40 + 5 - 100 + 20)

    def test_coverage_days_without_demand_sorts_last(self):
        suggestion = self._make_suggestion()
        self.assertGreater(suggestion._coverage_days(50.0, 0.0), 1000)
        self.assertAlmostEqual(suggestion._coverage_days(50.0, 5.0), 10.0)

    # ------------------------------------------------------------------
    # Restricciones del proveedor
    # ------------------------------------------------------------------
    def test_min_qty_raises_the_quantity(self):
        suggestion = self._make_suggestion()
        seller = self.product_a.seller_ids[0]
        seller.min_qty = 50
        qty = suggestion._apply_supplier_constraints(self.product_a, seller, 12.0)
        self.assertAlmostEqual(qty, 50.0)

    def test_packaging_rounds_up(self):
        suggestion = self._make_suggestion()
        self.env["product.packaging"].create({
            "name": "Caja x12", "product_id": self.product_a.id, "qty": 12,
            "purchase": True,
        })
        qty = suggestion._apply_supplier_constraints(
            self.product_a, self.product_a.seller_ids[0], 25.0)
        self.assertAlmostEqual(qty, 36.0)

    def test_min_qty_is_applied_before_packaging(self):
        """El resultado tiene que ser múltiplo del bulto y no menor al mínimo."""
        suggestion = self._make_suggestion()
        seller = self.product_a.seller_ids[0]
        seller.min_qty = 50
        self.env["product.packaging"].create({
            "name": "Caja x12", "product_id": self.product_a.id, "qty": 12,
            "purchase": True,
        })
        qty = suggestion._apply_supplier_constraints(self.product_a, seller, 12.0)
        self.assertAlmostEqual(qty, 60.0)
        self.assertEqual(qty % 12, 0)

    def test_smallest_packaging_wins(self):
        suggestion = self._make_suggestion()
        for name, size in (("Pallet", 120), ("Caja", 12)):
            self.env["product.packaging"].create({
                "name": name, "product_id": self.product_a.id, "qty": size,
                "purchase": True,
            })
        qty = suggestion._apply_supplier_constraints(
            self.product_a, self.product_a.seller_ids[0], 25.0)
        self.assertAlmostEqual(qty, 36.0)

    def test_non_purchase_packaging_is_ignored(self):
        suggestion = self._make_suggestion()
        self.env["product.packaging"].create({
            "name": "Caja de venta", "product_id": self.product_a.id, "qty": 12,
            "purchase": False,
        })
        qty = suggestion._apply_supplier_constraints(
            self.product_a, self.product_a.seller_ids[0], 25.0)
        self.assertAlmostEqual(qty, 25.0)

    def test_min_qty_is_converted_from_the_supplier_uom(self):
        """El mínimo del proveedor viene en su unidad, no en la de stock."""
        suggestion = self._make_suggestion()
        seller = self.product_a.seller_ids[0]
        seller.write({"product_uom": self.uom_dozen.id, "min_qty": 5})
        qty = suggestion._apply_supplier_constraints(self.product_a, seller, 12.0)
        self.assertAlmostEqual(qty, 60.0, msg="5 docenas son 60 unidades")

    def test_negative_quantity_becomes_zero(self):
        suggestion = self._make_suggestion()
        qty = suggestion._apply_supplier_constraints(
            self.product_a, self.product_a.seller_ids[0], -8.0)
        self.assertAlmostEqual(qty, 0.0)

    # ------------------------------------------------------------------
    # Integración
    # ------------------------------------------------------------------
    def test_compute_creates_lines_with_full_metrics(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()

        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.adu, 10.0, places=2)
        self.assertAlmostEqual(line.lead_time_days, 10.0,
                               msg="delay del supplierinfo")
        self.assertAlmostEqual(line.safety_stock, 5.0,
                               msg="piso de medio día con sigma cero")
        # 10/día x (10 de plazo + 30 de cobertura) + 5 de colchón, sin stock.
        self.assertAlmostEqual(line.qty_suggested, 405.0, places=1)
        self.assertAlmostEqual(line.qty_final, line.qty_suggested)
        self.assertEqual(line.supplier_id, self.supplier_a)
        self.assertEqual(line.method_used, "weighted_ma")
        self.assertTrue(line.explanation)
        self.assertTrue(line.params_snapshot)
        self.assertEqual(line.params_snapshot["coverage_days"], 30)
        self.assertEqual(suggestion.state, "computed")

    def test_products_with_enough_stock_get_no_line(self):
        self._sell_daily(self.product_a, 1, 91, 1)
        self._set_stock(self.product_a, 5000)
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        self.assertFalse(suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a))

    def test_compute_is_idempotent_on_metrics(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        first = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a).qty_suggested
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)
        self.assertEqual(len(line), 1, "No duplica la línea")
        self.assertAlmostEqual(line.qty_suggested, first)

    def test_compute_preserves_manual_quantity(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)
        line.qty_final = 12
        suggestion.action_compute()
        self.assertAlmostEqual(line.qty_final, 12.0)
        self.assertAlmostEqual(line.qty_suggested, 405.0, places=1)

    def test_packaging_reaches_the_suggested_line(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self.env["product.packaging"].create({
            "name": "Caja x12", "product_id": self.product_a.id, "qty": 12,
            "purchase": True,
        })
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)
        self.assertAlmostEqual(line.qty_suggested, math.ceil(405 / 12) * 12)
