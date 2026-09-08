# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestPurchaseGeneration(PurchaseAdvisorCommon):
    """Fase 1: el circuito sugerencia → revisión manual → órdenes por proveedor."""

    def test_sequence_assigned_on_create(self):
        suggestion = self._make_suggestion()
        self.assertTrue(suggestion.name.startswith("PS/"), suggestion.name)
        self.assertEqual(suggestion.state, "draft")

    def test_company_follows_warehouse(self):
        suggestion = self._make_suggestion()
        self.assertEqual(suggestion.company_id, self.warehouse.company_id)

    def test_totals_and_line_count(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_final": 10, "price_unit": 100.0},
            {"product_id": self.product_c.id, "supplier_id": self.supplier_b.id,
             "qty_final": 5, "price_unit": 80.0},
        ])
        self.assertEqual(suggestion.line_count, 2)
        self.assertAlmostEqual(suggestion.total_amount, 10 * 100.0 + 5 * 80.0)

    def test_orders_grouped_by_supplier(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_final": 10, "price_unit": 100.0},
            {"product_id": self.product_b.id, "supplier_id": self.supplier_a.id,
             "qty_final": 4, "price_unit": 250.0},
            {"product_id": self.product_c.id, "supplier_id": self.supplier_b.id,
             "qty_final": 7, "price_unit": 80.0},
        ])
        suggestion.action_compute()
        suggestion.action_confirm()
        suggestion.action_create_purchase_orders()

        orders = suggestion.purchase_order_ids
        self.assertEqual(len(orders), 2, "Dos proveedores tienen que dar dos órdenes")
        self.assertEqual(suggestion.state, "done")

        order_a = orders.filtered(lambda o: o.partner_id == self.supplier_a)
        order_b = orders.filtered(lambda o: o.partner_id == self.supplier_b)
        self.assertEqual(len(order_a.order_line), 2)
        self.assertEqual(len(order_b.order_line), 1)
        self.assertTrue(all(o.state == "draft" for o in orders),
                        "Las órdenes nunca se confirman solas")
        self.assertTrue(all(o.origin == suggestion.name for o in orders))
        self.assertEqual(
            order_a.picking_type_id, self.warehouse.in_type_id,
            "La orden entra por el almacén de la sugerencia")

    def test_zero_qty_lines_are_skipped(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_final": 10, "price_unit": 100.0},
            {"product_id": self.product_b.id, "supplier_id": self.supplier_a.id,
             "qty_final": 0, "price_unit": 250.0},
        ])
        suggestion.action_compute()
        suggestion.action_confirm()
        suggestion.action_create_purchase_orders()

        self.assertEqual(len(suggestion.purchase_order_ids.order_line), 1)
        self.assertEqual(
            suggestion.purchase_order_ids.order_line.product_id, self.product_a)
        self.assertTrue(suggestion.line_ids.filtered(lambda l: l.qty_final == 0),
                        "La línea descartada queda como registro")

    def test_line_without_supplier_blocks(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "qty_final": 10, "price_unit": 100.0},
        ])
        suggestion.action_compute()
        suggestion.action_confirm()
        with self.assertRaises(UserError):
            suggestion.action_create_purchase_orders()

    def test_confirm_without_quantities_blocks(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_final": 0},
        ])
        suggestion.action_compute()
        with self.assertRaises(UserError):
            suggestion.action_confirm()

    def test_cannot_create_orders_before_confirm(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_final": 10, "price_unit": 100.0},
        ])
        suggestion.action_compute()
        with self.assertRaises(UserError):
            suggestion.action_create_purchase_orders()

    def test_purchase_uom_conversion(self):
        """qty_final está en unidad de stock; la orden va en unidad de compra."""
        product = self._make_product(
            "Producto docena", self.supplier_a, price=60.0, uom_po=self.uom_dozen)
        suggestion = self._make_suggestion(lines=[
            {"product_id": product.id, "supplier_id": self.supplier_a.id,
             "qty_final": 24, "price_unit": 60.0},
        ])
        suggestion.action_compute()
        suggestion.action_confirm()
        suggestion.action_create_purchase_orders()

        pol = suggestion.purchase_order_ids.order_line
        self.assertEqual(pol.product_uom, self.uom_dozen)
        self.assertAlmostEqual(pol.product_qty, 2.0, msg="24 unidades son 2 docenas")

    def test_was_edited_flag(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_suggested": 10, "qty_final": 10, "price_unit": 100.0},
        ])
        line = suggestion.line_ids
        self.assertFalse(line.was_edited)
        line.qty_final = 15
        self.assertTrue(line.was_edited)

    def test_recompute_preserves_manual_edits(self):
        """El motor no puede pisar una cantidad que el usuario ya decidió."""
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_suggested": 10, "qty_final": 42, "price_unit": 100.0},
        ])
        line = suggestion.line_ids
        self.assertTrue(line.was_edited)
        preserved = suggestion._apply_metrics({
            self.product_a.id: {"qty_suggested": 8, "qty_final": 8, "adu": 1.5},
        })
        self.assertEqual(preserved, 1)
        self.assertAlmostEqual(line.qty_final, 42.0, msg="La edición manual gana")
        self.assertAlmostEqual(line.qty_suggested, 8.0, msg="Las métricas sí se actualizan")
        self.assertAlmostEqual(line.adu, 1.5)

    def test_done_suggestion_cannot_be_deleted(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_final": 10, "price_unit": 100.0},
        ])
        suggestion.action_compute()
        suggestion.action_confirm()
        suggestion.action_create_purchase_orders()
        with self.assertRaises(UserError):
            suggestion.unlink()

    def test_draft_blocked_while_orders_exist(self):
        suggestion = self._make_suggestion(lines=[
            {"product_id": self.product_a.id, "supplier_id": self.supplier_a.id,
             "qty_final": 10, "price_unit": 100.0},
        ])
        suggestion.action_compute()
        suggestion.action_confirm()
        suggestion.action_create_purchase_orders()
        with self.assertRaises(UserError):
            suggestion.action_draft()
