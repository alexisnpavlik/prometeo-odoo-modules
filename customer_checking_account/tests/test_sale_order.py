# -*- coding: utf-8 -*-
from datetime import date

from .common import CcaCommon


class TestSaleOrder(CcaCommon):

    def _withdrawal(self, product=None, qty=2, **vals):
        """Retiro en borrador con recargo 10%."""
        values = {
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "surcharge_percent": 10.0,
            "line_ids": [(0, 0, {"product_id": (product or self.product).id, "quantity": qty})],
        }
        values.update(vals)
        return self.env["cca.withdrawal"].create(values)

    def test_confirm_creates_confirmed_sale_order(self):
        """Confirmar crea una venta confirmada con los productos, el recargo y el mismo total."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        order = withdrawal.sale_order_id
        self.assertEqual(order.state, "sale")
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(order.origin, withdrawal.name)
        product_line = order.order_line.filtered(lambda l: l.product_id == self.product)
        self.assertEqual(product_line.product_uom_qty, 2.0)
        self.assertEqual(product_line.price_unit, 100.0)
        self.assertFalse(product_line.tax_id)
        surcharge = order.order_line - product_line
        self.assertEqual(surcharge.price_unit, 20.0)
        self.assertEqual(order.amount_total, withdrawal.amount_total)

    def test_stock_goes_through_sale_delivery(self):
        """El stock sale por la entrega de la venta, validada; no hay albarán aparte."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        order = withdrawal.sale_order_id
        self.assertEqual(withdrawal.picking_id, order.picking_ids)
        self.assertEqual(withdrawal.picking_id.state, "done")
        self.assertEqual(order.order_line.filtered(lambda l: l.product_id == self.product).qty_delivered, 2.0)

    def test_service_only_sale_without_delivery(self):
        """Solo servicios: venta confirmada sin entrega."""
        withdrawal = self._withdrawal(product=self.service, qty=1, surcharge_percent=0.0)
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.sale_order_id.state, "sale")
        self.assertFalse(withdrawal.picking_id)

    def test_cancel_returns_stock_and_cancels_sale(self):
        """Devolver devuelve el stock y cancela la venta."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        order = withdrawal.sale_order_id
        withdrawal.action_cancel()
        self.assertEqual(order.state, "cancel")
        self.assertEqual(withdrawal.return_picking_id.state, "done")

    def test_edit_cancels_sale_and_reconfirm_creates_new(self):
        """Editar cancela la venta; al reconfirmar se crea una nueva."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        first = withdrawal.sale_order_id
        withdrawal.action_edit()
        self.assertEqual(first.state, "cancel")
        self.assertFalse(withdrawal.sale_order_id)
        withdrawal.action_confirm()
        self.assertNotEqual(withdrawal.sale_order_id, first)
        self.assertEqual(withdrawal.sale_order_id.state, "sale")
