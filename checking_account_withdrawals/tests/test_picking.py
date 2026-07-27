# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawPicking(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.company.caw_installment_count = 1
        self.company.caw_picking_type_id = self.warehouse.out_type_id

    def _confirmed(self, qty=3.0, price=100.0):
        """Retiro confirmado de `qty` unidades del producto de prueba."""
        withdrawal = self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": qty,
                "price_unit": price,
            })],
        })
        withdrawal.action_confirm()
        return withdrawal

    def test_confirm_creates_outgoing_picking(self):
        """Confirmar el retiro genera un albarán de salida con las mismas líneas."""
        withdrawal = self._confirmed(qty=3.0)
        picking = withdrawal.picking_id
        self.assertTrue(picking)
        self.assertEqual(picking.picking_type_id.code, "outgoing")
        self.assertEqual(picking.partner_id, self.partner)
        self.assertEqual(len(picking.move_ids), 1)
        self.assertEqual(picking.move_ids.product_id, self.product)
        self.assertEqual(picking.move_ids.product_uom_qty, 3.0)

    def test_stock_is_not_deducted_on_confirm(self):
        """El descuento de stock ocurre al validar el albarán, no al confirmar el retiro."""
        withdrawal = self._confirmed()
        self.assertNotEqual(withdrawal.picking_id.state, "done")

    def test_cancelled_picking_flags_inconsistency(self):
        """Si el albarán se cancela con el retiro vivo, queda señalizado para revisión."""
        withdrawal = self._confirmed()
        withdrawal.picking_id.action_cancel()
        withdrawal.invalidate_recordset()
        self.assertEqual(withdrawal.picking_state, "cancel")
        self.assertTrue(withdrawal.is_inconsistent)

    def test_picking_type_falls_back_to_warehouse(self):
        """Sin tipo configurado en la compañía se usa el de salidas del almacén."""
        self.company.caw_picking_type_id = False
        withdrawal = self._confirmed()
        self.assertEqual(withdrawal.picking_id.picking_type_id, self.warehouse.out_type_id)
