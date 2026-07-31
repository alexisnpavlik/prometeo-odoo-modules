# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSalePicking(CviCommon):

    def setUp(self):
        super().setUp()
        self.stock_location = self.warehouse.lot_stock_id
        self.vendor_location = self.vendor_user._cvi_get_location()

    def _stock_vendor(self, quantity):
        """Deja `quantity` unidades del mueble en poder del vendedor."""
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": self.vendor_location.id,
            "inventory_quantity": quantity,
        })
        quant.action_apply_inventory()

    def _available(self, location):
        return self.env["stock.quant"]._get_available_quantity(self.product, location)

    def _card(self, **kwargs):
        vals = {
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "quantity": 1.0,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        return self.env["cvi.card"].create(vals)

    def test_confirming_creates_a_validated_picking(self):
        """Confirmar la venta genera el albarán que saca el mueble del vendedor."""
        self._stock_vendor(2)
        card = self._card()
        card.action_confirm()
        self.assertTrue(card.picking_id)
        self.assertEqual(card.picking_id.state, "done")

    def test_sale_reduces_vendor_stock(self):
        """El mueble vendido deja de figurar a cargo del vendedor (HU-03)."""
        self._stock_vendor(2)
        card = self._card(quantity=1.0)
        card.action_confirm()
        self.assertEqual(self._available(self.vendor_location), 1)

    def test_sale_picking_goes_to_customer_location(self):
        """El albarán de venta lleva el mueble a la ubicación de clientes."""
        self._stock_vendor(2)
        card = self._card()
        card.action_confirm()
        customers = self.env.ref("stock.stock_location_customers")
        self.assertEqual(card.picking_id.location_dest_id, customers)

    def test_selling_without_stock_is_rejected(self):
        """El vendedor no puede vender un mueble que no retiró de fábrica."""
        broke_vendor = self.env["res.users"].create({
            "name": "Vendedor Sin Stock",
            "login": "cvi_vendor_nostock",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        card = self._card(vendor_id=broke_vendor.id)
        with self.assertRaises(UserError):
            card.action_confirm()

    def test_failed_confirm_leaves_no_installments(self):
        """Si el descuento de stock falla, la tarjeta no queda con cuotas a medias."""
        broke_vendor = self.env["res.users"].create({
            "name": "Vendedor Sin Stock",
            "login": "cvi_vendor_nostock2",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        card = self._card(vendor_id=broke_vendor.id)
        with self.assertRaises(UserError):
            card.action_confirm()
        self.assertEqual(card.state, "draft")
        self.assertFalse(card.installment_ids)
        self.assertFalse(card.payment_ids)

    def test_multiple_units_are_discounted(self):
        """Una venta de 2 unidades descuenta 2 del stock del vendedor."""
        self._stock_vendor(5)
        card = self._card(quantity=2.0)
        card.action_confirm()
        self.assertEqual(self._available(self.vendor_location), 3)

    def _report_quants(self):
        """Lo que lista el reporte de mercadería en la calle (mismo dominio que la acción)."""
        return self.env["stock.quant"].search([
            ("location_id.cvi_is_vendor_location", "=", True),
        ])

    def test_vendor_location_is_marked_as_such(self):
        """La ubicación del vendedor queda marcada, que es lo que filtra el reporte."""
        self.assertTrue(self.vendor_location.cvi_is_vendor_location)

    def test_vendor_stock_report_shows_remaining_units(self):
        """El reporte de mercadería en la calle muestra retirado menos vendido (HU-03)."""
        self._stock_vendor(5)
        card = self._card(quantity=2.0)
        card.action_confirm()
        vendor_quants = self._report_quants().filtered(
            lambda q: q.location_id == self.vendor_location
            and q.product_id == self.product
        )
        self.assertEqual(sum(vendor_quants.mapped("quantity")), 3)

    def test_report_excludes_factory_stock(self):
        """El reporte solo mira ubicaciones de vendedores, no el stock de fábrica."""
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": self.stock_location.id,
            "inventory_quantity": 7,
        })
        quant.action_apply_inventory()
        self.assertNotIn(self.stock_location, self._report_quants().mapped("location_id"))

    def test_report_action_uses_the_same_domain(self):
        """La acción del menú filtra por el mismo marcador que verifican estos tests."""
        action = self.env.ref(
            "collections_from_vendors_installments.action_cvi_vendor_stock"
        )
        self.assertIn("cvi_is_vendor_location", action.domain)
