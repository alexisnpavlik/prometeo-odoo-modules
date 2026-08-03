# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviDeliveryReversal(CviCommon):

    def setUp(self):
        super().setUp()
        self.stock_location = self.warehouse.lot_stock_id

    def _receive(self, quantity):
        """Ingresa producción a WH/Stock por ajuste de inventario."""
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": self.stock_location.id,
            "inventory_quantity": quantity,
        })
        quant.action_apply_inventory()
        return quant

    def _available(self, location):
        return self.env["stock.quant"]._get_available_quantity(self.product, location)

    def _deliver(self, quantity, direction="out", vendor=None):
        wizard = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": (vendor or self.vendor_user).id,
            "direction": direction,
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": quantity})],
        })
        action = wizard.action_confirm_delivery()
        return self.env["stock.picking"].browse(action["params"]["next"]["res_id"])

    def _fresh_vendor(self, login):
        """Vendedor sin stock previo.

        self.vendor_user no sirve para probar faltantes: common.py le siembra 500
        unidades en su ubicación, así que siempre tiene de sobra para revertir.
        """
        return self.env["res.users"].create({
            "name": "Vendedor %s" % login,
            "login": login,
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def test_reversal_returns_the_goods_to_the_factory(self):
        """Anular una entrega devuelve la mercadería a fábrica."""
        self._receive(10)
        before_factory = self._available(self.stock_location)
        before_vendor = self._available(self.vendor_location)
        picking = self._deliver(3)
        picking.action_cvi_reverse_delivery()
        self.assertEqual(self._available(self.stock_location), before_factory)
        self.assertEqual(self._available(self.vendor_location), before_vendor)

    def test_reversal_links_both_pickings(self):
        """La entrega y su anulación quedan enlazadas en las dos direcciones."""
        self._receive(10)
        picking = self._deliver(3)
        picking.action_cvi_reverse_delivery()
        reversal = picking.cvi_reversal_id
        self.assertTrue(reversal)
        self.assertEqual(reversal.state, "done")
        self.assertEqual(reversal.cvi_reversed_id, picking)

    def test_original_picking_stays_done(self):
        """Anular no borra ni cancela el albarán original: la trazabilidad se conserva."""
        self._receive(10)
        picking = self._deliver(3)
        picking.action_cvi_reverse_delivery()
        self.assertEqual(picking.state, "done")
        self.assertTrue(picking.exists())

    def test_cannot_reverse_twice(self):
        """Una entrega ya anulada no se vuelve a anular."""
        self._receive(10)
        picking = self._deliver(3)
        picking.action_cvi_reverse_delivery()
        with self.assertRaises(UserError):
            picking.action_cvi_reverse_delivery()

    def test_cannot_reverse_a_reversal(self):
        """Anular una anulación volvería a entregar la mercadería: no se permite."""
        self._receive(10)
        picking = self._deliver(3)
        picking.action_cvi_reverse_delivery()
        with self.assertRaises(UserError):
            picking.cvi_reversal_id.action_cvi_reverse_delivery()

    def test_cannot_reverse_when_goods_are_gone(self):
        """Si el vendedor ya no tiene la mercadería, la anulación se rechaza con motivo.

        Sin _cvi_check_reversible Odoo no se queja: valida el albarán inverso igual y
        deja la ubicación del vendedor en negativo. Verificado desactivando el chequeo.
        """
        vendor = self._fresh_vendor("cvi_vendor_goods_gone")
        self._receive(10)
        picking = self._deliver(3, vendor=vendor)
        # El vendedor devuelve todo por la vía normal: ya no tiene esas unidades.
        self._deliver(3, direction="in", vendor=vendor)
        self.assertEqual(self._available(vendor.cvi_stock_location_id), 0)
        with self.assertRaises(UserError):
            picking.action_cvi_reverse_delivery()

    def test_reversal_is_rejected_on_a_foreign_picking(self):
        """Un albarán que no mueve mercadería de vendedores no se anula por acá."""
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.int_type_id.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id,
        })
        self.assertFalse(picking.cvi_is_vendor_move)
        with self.assertRaises(UserError):
            picking.action_cvi_reverse_delivery()

    def test_draft_picking_cannot_be_reversed(self):
        """Un albarán sin validar se cancela con el botón estándar, no se anula."""
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.int_type_id.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.vendor_location.id,
        })
        self.assertTrue(picking.cvi_is_vendor_move)
        self.assertEqual(picking.state, "draft")
        with self.assertRaises(UserError):
            picking.action_cvi_reverse_delivery()

    def test_manager_can_reverse(self):
        """El administrador puede anular una entrega con sus propios permisos.

        Corre con with_user y no como el usuario de tests, que es superusuario y
        saltearía tanto las ir.rule como los permisos de stock.
        """
        manager = self.env["res.users"].create({
            "name": "Admin Anulación Test",
            "login": "cvi_manager_reversal_test",
            "email": "manager_reversal@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_manager").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self._receive(10)
        picking = self._deliver(3)
        picking.with_user(manager).action_cvi_reverse_delivery()
        self.assertTrue(picking.cvi_reversal_id)

    def test_reversal_action_is_consumable_by_the_web_client(self):
        """La notificación de anulación trae una act_window completa.

        clean_action() genera "views" solo para la acción de nivel superior. Acá la de
        arriba es ir.actions.client, así que la act_window anidada tiene que traerlo
        puesto: sin eso el cliente web falla en action.views.map() y el usuario ve un
        UncaughtPromiseError en vez del albarán.
        """
        self._receive(10)
        picking = self._deliver(3)
        action = picking.action_cvi_reverse_delivery()
        self.assertEqual(action["tag"], "display_notification")
        nxt = action["params"]["next"]
        self.assertEqual(nxt["type"], "ir.actions.act_window")
        self.assertTrue(nxt.get("views"))
        self.assertEqual(nxt["views"][0][1], "form")
