# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class PurchaseAdvisorCommon(TransactionCase):
    """Fixtures compartidas: un almacén, dos proveedores y productos comprables."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1)
        cls.supplier_a = cls.env["res.partner"].create({"name": "Proveedor A"})
        cls.supplier_b = cls.env["res.partner"].create({"name": "Proveedor B"})
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")

        cls.product_a = cls._make_product("Producto A", cls.supplier_a, price=100.0)
        cls.product_b = cls._make_product("Producto B", cls.supplier_a, price=250.0)
        cls.product_c = cls._make_product("Producto C", cls.supplier_b, price=80.0)

    @classmethod
    def _make_product(cls, name, supplier, price=100.0, uom_po=None):
        product = cls.env["product.product"].create({
            "name": name,
            "type": "consu",
            "is_storable": True,
            "purchase_ok": True,
            "uom_id": cls.uom_unit.id,
            "uom_po_id": (uom_po or cls.uom_unit).id,
            "standard_price": price * 0.7,
            "list_price": price,
        })
        cls.env["product.supplierinfo"].create({
            "partner_id": supplier.id,
            "product_tmpl_id": product.product_tmpl_id.id,
            "price": price,
            "delay": 10,
        })
        return product

    def _make_suggestion(self, lines=None, **kwargs):
        """Crea una sugerencia con líneas manuales listas para confirmar."""
        vals = {
            "warehouse_id": self.warehouse.id,
            "coverage_days": 30,
        }
        vals.update(kwargs)
        suggestion = self.env["prometeo.purchase.suggestion"].create(vals)
        for line_vals in lines or []:
            self.env["prometeo.purchase.suggestion.line"].create(
                dict(line_vals, suggestion_id=suggestion.id))
        return suggestion
