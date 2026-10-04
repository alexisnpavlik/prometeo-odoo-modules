# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMainVendor(TransactionCase):
    """El campo Proveedor de la ficha lee y escribe la primera línea de seller_ids."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor_a = cls.env["res.partner"].create({"name": "Proveedor A"})
        cls.vendor_b = cls.env["res.partner"].create({"name": "Proveedor B"})
        cls.vendor_c = cls.env["res.partner"].create({"name": "Proveedor C"})
        cls.template = cls.env["product.template"].create({
            "name": "Producto test",
            "purchase_ok": True,
            "standard_price": 123.0,
            "seller_ids": [
                (0, 0, {"partner_id": cls.vendor_b.id, "sequence": 5, "price": 50.0}),
                (0, 0, {"partner_id": cls.vendor_a.id, "sequence": 10, "price": 40.0}),
            ],
        })

    def _ordered_partners(self):
        """Proveedores de la ficha en el orden en que los elige Odoo."""
        sellers = self.template.seller_ids.sorted(lambda s: (s.sequence, s.id))
        return sellers.mapped("partner_id")

    def test_reads_lowest_sequence(self):
        """Muestra el proveedor con menor secuencia."""
        self.assertEqual(self.template.main_vendor_id, self.vendor_b)

    def test_ignores_variant_specific_lines(self):
        """Una línea atada a una variante no cuenta como proveedor principal."""
        self.env["product.supplierinfo"].create({
            "partner_id": self.vendor_c.id,
            "product_tmpl_id": self.template.id,
            "product_id": self.template.product_variant_id.id,
            "sequence": 1,
        })
        self.assertEqual(self.template.main_vendor_id, self.vendor_b)

    def test_existing_vendor_moves_to_top(self):
        """Elegir un proveedor ya cargado lo sube sin duplicar líneas ni tocar precios."""
        self.template.main_vendor_id = self.vendor_a
        self.assertEqual(len(self.template.seller_ids), 2)
        self.assertEqual(self._ordered_partners(), self.vendor_a | self.vendor_b)
        self.assertEqual(self._ordered_partners()[0], self.vendor_a)
        line_a = self.template.seller_ids.filtered(lambda s: s.partner_id == self.vendor_a)
        self.assertEqual(line_a.price, 40.0)
        self.assertEqual(self.template.main_vendor_id, self.vendor_a)

    def test_new_vendor_creates_first_line(self):
        """Un proveedor nuevo crea una línea primera con el costo del producto."""
        self.template.main_vendor_id = self.vendor_c
        self.assertEqual(len(self.template.seller_ids), 3)
        self.assertEqual(self._ordered_partners()[0], self.vendor_c)
        line_c = self.template.seller_ids.filtered(lambda s: s.partner_id == self.vendor_c)
        self.assertEqual(line_c.price, 123.0)
        self.assertEqual(line_c.company_id, self.env.company)

    def test_create_with_vendor(self):
        """Crear un producto con proveedor deja su línea cargada."""
        template = self.env["product.template"].create({
            "name": "Producto nuevo",
            "main_vendor_id": self.vendor_a.id,
        })
        self.assertEqual(template.seller_ids.partner_id, self.vendor_a)

    def test_clearing_keeps_lines(self):
        """Vaciar el campo no borra ninguna línea de proveedor."""
        self.template.main_vendor_id = False
        self.assertEqual(len(self.template.seller_ids), 2)
        self.assertEqual(self.template.main_vendor_id, self.vendor_b)
