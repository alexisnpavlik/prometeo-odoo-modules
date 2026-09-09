# -*- coding: utf-8 -*-
import math
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from .common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestQuantity(PurchaseAdvisorCommon):
    """Fase 3: lead time medido, stock de seguridad y restricciones del proveedor."""

    def test_product_without_supplier_is_calculated_with_warning(self):
        """La falta de proveedor no oculta una necesidad real de reposición."""
        product = self.product_no_seller
        product.standard_price = 25
        self._sell_daily(product, 2, 31, 1)
        suggestion = self._make_suggestion()
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(lambda row: row.product_id == product)
        self.assertEqual(len(line), 1)
        self.assertGreater(line.qty_suggested, 0)
        self.assertFalse(line.supplier_id)
        self.assertEqual(line.price_unit, 0)
        self.assertIn("Sin proveedor", line.warnings)
        self.assertIn("no tienen proveedor", suggestion.calculation_notes)
        self.assertNotIn("fuera del cálculo", suggestion.calculation_notes)

    def test_configured_lead_time_is_per_product(self):
        """Compartir proveedor no implica compartir plazo entre productos."""
        self._sell_daily(self.product_a, 1, 31, 1)
        self._sell_daily(self.product_b, 1, 31, 1)
        self.product_a.seller_ids.delay = 2
        self.product_b.seller_ids.delay = 20
        suggestion = self._make_suggestion()
        suggestion.action_compute()
        lines = {line.product_id.id: line for line in suggestion.line_ids}
        self.assertEqual(lines[self.product_a.id].lead_time_days, 2)
        self.assertEqual(lines[self.product_b.id].lead_time_days, 20)

    def test_excluded_product_is_removed_on_recompute(self):
        """Excluir un producto no debe dejar su cantidad anterior lista para comprar."""
        self._sell_daily(self.product_a, 1, 31, 1)
        suggestion = self._make_suggestion()
        suggestion.action_compute()
        self.product_a.exclude_from_suggestion = True
        suggestion.action_compute()
        self.assertFalse(suggestion.line_ids.filtered(lambda line: line.product_id == self.product_a))

    def test_supplier_price_is_normalized_to_stock_unit(self):
        """Un precio de 120 por docena equivale a 10 por unidad en la sugerencia."""
        self.product_a.uom_po_id = self.uom_dozen
        self.product_a.seller_ids.price = 120
        self._sell_daily(self.product_a, 1, 31, 1)
        suggestion = self._make_suggestion()
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(lambda line: line.product_id == self.product_a)
        self.assertEqual(line.price_unit, 10)
        line.qty_final = 24
        self.assertEqual(line.subtotal, 240)
        suggestion.action_confirm()
        suggestion.action_create_purchase_orders()
        self.assertEqual(suggestion.purchase_order_ids.order_line.price_unit, 120)

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

        seller = self.product_a.seller_ids[0]
        used, source = self.supplier_a._lead_time_for_suggestion(
            {self.supplier_a.id: seller})[self.supplier_a.id]
        self.assertAlmostEqual(used, 12.0, places=1)
        self.assertEqual(source, "measured")

    def test_same_day_receipts_do_not_count_as_a_lead_time(self):
        """Si la orden se carga cuando la mercadería ya llegó, no hay plazo que
        medir: el promedio da minutos y haría desaparecer el stock de seguridad."""
        for _index in range(4):
            self._receive_po(self.supplier_a, self.product_a, 5, 30, 30)
        measured = self.supplier_a._measure_lead_times()
        days, sample = measured[self.supplier_a.id]
        self.assertEqual(sample, 4)
        self.assertLess(days, 1.0)

        seller = self.product_a.seller_ids[0]
        used, source = self.supplier_a._lead_time_for_suggestion(
            {self.supplier_a.id: seller})[self.supplier_a.id]
        self.assertAlmostEqual(used, 10.0, msg="cae al delay configurado")
        self.assertEqual(source, "configured")

    def test_unmeasurable_lead_time_is_reported_on_the_line(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self.product_a.seller_ids.delay = 0
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)
        self.assertAlmostEqual(line.lead_time_days, 7.0)
        self.assertIn("no se pudo medir", (line.warnings or "").lower())

    def test_small_sample_falls_back_to_configured_delay(self):
        """Con una sola orden el promedio no significa nada: manda el configurado."""
        self._receive_po(self.supplier_a, self.product_a, 5, 40, 28)
        seller = self.product_a.seller_ids[0]
        days, source = self.supplier_a._lead_time_for_suggestion(
            {self.supplier_a.id: seller})[self.supplier_a.id]
        self.assertAlmostEqual(days, 10.0, msg="delay del supplierinfo")
        self.assertEqual(source, "configured")

    def test_without_history_or_config_uses_one_week(self):
        seller = self.product_a.seller_ids[0]
        seller.delay = 0
        days, source = self.supplier_a._lead_time_for_suggestion(
            {self.supplier_a.id: seller})[self.supplier_a.id]
        self.assertAlmostEqual(days, 7.0)
        self.assertEqual(source, "fallback")

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
    # Proveedor en otra compañía
    # ------------------------------------------------------------------
    def test_seller_of_another_company_is_still_used(self):
        """La lista de precios de compra suele estar centralizada en una sola
        compañía, no cargada en cada sucursal."""
        other_company = self.env["res.company"].create({"name": "Casa central"})
        product = self.env["product.product"].create({
            "name": "Centralizado", "type": "consu", "is_storable": True,
            "purchase_ok": True,
        })
        self.env["product.supplierinfo"].create({
            "partner_id": self.supplier_a.id,
            "product_tmpl_id": product.product_tmpl_id.id,
            "company_id": other_company.id,
            "price": 150.0, "delay": 12,
        })
        suggestion = self._make_suggestion()
        seller = suggestion._pick_seller(product)
        self.assertTrue(seller, "Un proveedor de otra compañía sigue sirviendo")
        self.assertEqual(seller.partner_id, self.supplier_a)

    def test_seller_of_own_company_wins(self):
        """Si la sucursal negoció su propio precio, ese manda."""
        other_company = self.env["res.company"].create({"name": "Casa central 2"})
        product = self.env["product.product"].create({
            "name": "Con precio propio", "type": "consu", "is_storable": True,
            "purchase_ok": True,
        })
        self.env["product.supplierinfo"].create({
            "partner_id": self.supplier_a.id,
            "product_tmpl_id": product.product_tmpl_id.id,
            "company_id": other_company.id, "price": 150.0, "sequence": 1,
        })
        self.env["product.supplierinfo"].create({
            "partner_id": self.supplier_b.id,
            "product_tmpl_id": product.product_tmpl_id.id,
            "company_id": self.company.id, "price": 900.0, "sequence": 9,
        })
        suggestion = self._make_suggestion()
        seller = suggestion._pick_seller(product)
        self.assertEqual(seller.partner_id, self.supplier_b)

    # ------------------------------------------------------------------
    # Stock negativo
    # ------------------------------------------------------------------
    def test_negative_stock_does_not_inflate_the_quantity(self):
        """Stock negativo son recepciones sin registrar, no demanda a cubrir."""
        suggestion = self._make_suggestion(coverage_days=30)
        qty = suggestion._target_quantity(
            self._estimate_stub(adu=0.33), lead_time_days=10.0,
            safety_stock=0.0, on_hand=-473.0, incoming=0.0, outgoing=0.0)
        self.assertAlmostEqual(qty, 0.33 * 40, places=2,
                               msg="El faltante negativo no se compra de vuelta")

    def test_negative_stock_has_no_coverage(self):
        suggestion = self._make_suggestion()
        self.assertAlmostEqual(suggestion._coverage_days(-473.0, 0.33), 0.0)

    def test_negative_stock_is_reported_on_the_line(self):
        self._sell_daily(self.product_a, 1, 91, 1)
        self._set_stock(self.product_a, -50)
        suggestion = self._make_suggestion(coverage_days=30)
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(
            lambda l: l.product_id == self.product_a)
        self.assertTrue(line, "La línea se crea igual")
        self.assertAlmostEqual(line.qty_on_hand, -50.0,
                               msg="El campo muestra la verdad")
        self.assertIn("negativo", (line.warnings or "").lower())

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
