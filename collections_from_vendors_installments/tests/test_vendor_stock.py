# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviVendorStock(CviCommon):

    def setUp(self):
        super().setUp()
        self.stock_location = self.warehouse.lot_stock_id

    def _receive(self, quantity, product=None):
        """Ingresa producción a WH/Stock por ajuste de inventario (HU-01)."""
        product = product or self.product
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": product.id,
            "location_id": self.stock_location.id,
            "inventory_quantity": quantity,
        })
        quant.action_apply_inventory()
        return quant

    def _available(self, location, product=None):
        """Cantidad disponible de un producto en una ubicación."""
        product = product or self.product
        return self.env["stock.quant"]._get_available_quantity(product, location)

    def _deliver(self, quantity, direction="out", vendor=None):
        """Corre el wizard de entrega/devolución y devuelve el albarán generado."""
        wizard = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": (vendor or self.vendor_user).id,
            "direction": direction,
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": quantity})],
        })
        return self._picking_from_action(wizard.action_confirm_delivery())

    def _picking_from_action(self, action):
        """Extrae el albarán de la notificación que devuelve el wizard.

        Chequea también que la act_window anidada traiga "views": clean_action() solo
        lo genera para la acción de nivel superior, y acá la de arriba es
        ir.actions.client. Sin "views" el cliente web falla en action.views.map().
        """
        self.assertEqual(action["tag"], "display_notification")
        nxt = action["params"]["next"]
        self.assertEqual(nxt["res_model"], "stock.picking")
        self.assertTrue(nxt.get("views"), "la acción anidada tiene que traer views")
        return self.env["stock.picking"].browse(nxt["res_id"])

    def test_production_intake_increases_factory_stock(self):
        """Ingresar producción actualiza el stock disponible de fábrica (HU-01)."""
        before = self._available(self.stock_location)
        self._receive(10)
        self.assertEqual(self._available(self.stock_location), before + 10)

    def test_product_has_no_individual_tracking(self):
        """Los muebles no se identifican por unidad: sin lotes ni series (HU-01)."""
        self.assertEqual(self.product.tracking, "none")

    def test_vendor_location_is_created_on_demand(self):
        """La ubicación del vendedor se crea la primera vez que se la necesita."""
        fresh_vendor = self.env["res.users"].create({
            "name": "Vendedor Sin Ubicación",
            "login": "cvi_vendor_fresh_location",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.assertFalse(fresh_vendor.cvi_stock_location_id)
        location = fresh_vendor._cvi_get_location()
        self.assertTrue(location)
        self.assertEqual(location.usage, "internal")
        self.assertEqual(fresh_vendor.cvi_stock_location_id, location)

    def test_vendor_location_is_reused(self):
        """La segunda llamada devuelve la misma ubicación, no crea otra."""
        first = self.vendor_user._cvi_get_location()
        second = self.vendor_user._cvi_get_location()
        self.assertEqual(first, second)

    def test_vendor_location_creation_is_idempotent(self):
        """Llamar dos veces seguidas no deja ubicaciones huérfanas marcadas.

        No es un test de concurrencia real (no se pueden lanzar threads en
        TransactionCase): cubre que el path sea idempotente. La protección
        contra la carrera concurrente es el FOR UPDATE en _cvi_get_location.
        """
        self.vendor_user._cvi_get_location()
        self.vendor_user._cvi_get_location()
        vendor_locations = self.env["stock.location"].search([
            ("cvi_is_vendor_location", "=", True),
            ("name", "=", self.vendor_user.name),
        ])
        self.assertEqual(len(vendor_locations), 1)

    def test_vendor_location_hangs_from_vendors_parent(self):
        """La ubicación del vendedor cuelga de la ubicación vista Vendedores."""
        parent = self.env.ref("collections_from_vendors_installments.stock_location_vendors")
        self.assertEqual(self.vendor_user._cvi_get_location().location_id, parent)

    def test_delivery_moves_stock_from_factory_to_vendor(self):
        """Entregar mercadería la pasa de fábrica al vendedor (HU-02)."""
        vendor_location = self.vendor_user._cvi_get_location()
        before = self._available(vendor_location)
        self._receive(10)
        self._deliver(3)
        self.assertEqual(self._available(vendor_location), before + 3)

    def test_delivery_reduces_factory_stock(self):
        """Lo entregado deja de estar disponible en fábrica (HU-02)."""
        self._receive(10)
        before = self._available(self.stock_location)
        self._deliver(3)
        self.assertEqual(self._available(self.stock_location), before - 3)

    def test_delivery_produces_a_validated_picking(self):
        """La entrega genera un albarán hecho, que sirve de constancia (HU-02, RN-08)."""
        self._receive(10)
        picking = self._deliver(3)
        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.location_dest_id, self.vendor_user._cvi_get_location())

    def test_delivering_more_than_available_is_rejected(self):
        """No se puede entregar más unidades de las disponibles en fábrica (HU-02)."""
        self._receive(2)
        with self.assertRaises(UserError):
            self._deliver(5)

    def test_delivery_without_lines_is_rejected(self):
        """No se confirma una entrega vacía."""
        wizard = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": self.vendor_user.id,
            "direction": "out",
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_delivery()

    def test_zero_quantity_line_is_rejected(self):
        """Una línea con cantidad cero o negativa no es una entrega válida."""
        with self.assertRaises(UserError):
            self._deliver(0)

    def test_return_moves_stock_back_to_factory(self):
        """La devolución del vendedor reingresa el stock a fábrica (HU-04)."""
        vendor_location = self.vendor_user._cvi_get_location()
        before = self._available(vendor_location)
        self._receive(10)
        self._deliver(4)
        self._deliver(4, direction="in")
        self.assertEqual(self._available(vendor_location), before)

    def test_return_increases_factory_stock(self):
        """Lo devuelto vuelve a estar disponible en fábrica (HU-04)."""
        self._receive(10)
        self._deliver(4)
        before = self._available(self.stock_location)
        self._deliver(4, direction="in")
        self.assertEqual(self._available(self.stock_location), before + 4)

    def test_returning_more_than_the_vendor_holds_is_rejected(self):
        """El vendedor no puede devolver más de lo que tiene a cargo (HU-04)."""
        fresh_vendor = self.env["res.users"].create({
            "name": "Vendedor Devolución Test",
            "login": "cvi_vendor_return_test",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self._receive(10)
        self._deliver(2, vendor=fresh_vendor)
        with self.assertRaises(UserError):
            self._deliver(5, direction="in", vendor=fresh_vendor)

    def test_vendor_sees_only_his_own_stock(self):
        """El vendedor ve la mercadería de su ubicación, no la de otros (HU-02)."""
        other_vendor = self.env["res.users"].create({
            "name": "Otro Vendedor Test",
            "login": "cvi_vendor_other_test",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self._receive(10)
        self._deliver(3, vendor=other_vendor)

        action = self.env["stock.quant"].with_user(self.vendor_user).cvi_action_my_stock()
        self.assertEqual(action["domain"], [("location_id", "=", self.vendor_location.id)])
        # El vendedor no es stock.group_stock_user: esta búsqueda falla si le falta
        # el permiso de lectura sobre stock.quant.
        quants = self.env["stock.quant"].with_user(self.vendor_user).search(action["domain"])
        self.assertEqual(quants.mapped("location_id"), self.vendor_location)
        self.assertNotIn(
            other_vendor.cvi_stock_location_id, quants.mapped("location_id")
        )

    def test_opening_my_stock_does_not_create_a_location(self):
        """Abrir el listado no provisiona la ubicación del vendedor (HU-02)."""
        fresh_vendor = self.env["res.users"].create({
            "name": "Vendedor Sin Retiro Test",
            "login": "cvi_vendor_nostock_test",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.assertFalse(fresh_vendor.cvi_stock_location_id)

        action = self.env["stock.quant"].with_user(fresh_vendor).cvi_action_my_stock()
        self.assertFalse(
            self.env["stock.quant"].with_user(fresh_vendor).search(action["domain"])
        )
        fresh_vendor.invalidate_recordset(["cvi_stock_location_id"])
        self.assertFalse(fresh_vendor.cvi_stock_location_id)
