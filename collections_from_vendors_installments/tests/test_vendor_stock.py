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
        """Corre el wizard de entrega/devolución de mercadería."""
        wizard = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": (vendor or self.vendor_user).id,
            "direction": direction,
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": quantity})],
        })
        return wizard.action_confirm_delivery()

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
        self.assertFalse(self.vendor_user.cvi_stock_location_id)
        location = self.vendor_user._cvi_get_location()
        self.assertTrue(location)
        self.assertEqual(location.usage, "internal")
        self.assertEqual(self.vendor_user.cvi_stock_location_id, location)

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
        self._receive(10)
        self._deliver(3)
        vendor_location = self.vendor_user._cvi_get_location()
        self.assertEqual(self._available(vendor_location), 3)

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
        self._receive(10)
        self._deliver(4)
        vendor_location = self.vendor_user._cvi_get_location()
        self._deliver(4, direction="in")
        self.assertEqual(self._available(vendor_location), 0)

    def test_return_increases_factory_stock(self):
        """Lo devuelto vuelve a estar disponible en fábrica (HU-04)."""
        self._receive(10)
        self._deliver(4)
        before = self._available(self.stock_location)
        self._deliver(4, direction="in")
        self.assertEqual(self._available(self.stock_location), before + 4)

    def test_returning_more_than_the_vendor_holds_is_rejected(self):
        """El vendedor no puede devolver más de lo que tiene a cargo (HU-04)."""
        self._receive(10)
        self._deliver(2)
        with self.assertRaises(UserError):
            self._deliver(5, direction="in")
