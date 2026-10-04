# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPricelistLines(TransactionCase):
    """La tabla de la ficha lee y escribe reglas de precio fijo del producto."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pricelist_a = cls.env["product.pricelist"].create({"name": "Lista A"})
        cls.pricelist_b = cls.env["product.pricelist"].create({"name": "Lista B"})
        cls.template = cls.env["product.template"].create({
            "name": "Producto test",
            "list_price": 100.0,
        })

    def test_create_from_form_applies_to_product(self):
        """Una fila nueva queda como regla fija del producto en la lista elegida."""
        self.template.write({"pricelist_line_ids": [
            (0, 0, {"pricelist_id": self.pricelist_a.id, "fixed_price": 80.0}),
        ]})
        item = self.template.pricelist_line_ids
        self.assertEqual(item.applied_on, "1_product")
        self.assertEqual(item.compute_price, "fixed")
        self.assertEqual(item.pricelist_id, self.pricelist_a)
        self.assertEqual(self.pricelist_a._get_product_price(
            self.template.product_variant_id, 1.0), 80.0)

    def test_hides_non_fixed_and_variant_rules(self):
        """Reglas por fórmula o de variante no aparecen en la tabla."""
        Item = self.env["product.pricelist.item"]
        fixed = Item.create({
            "pricelist_id": self.pricelist_a.id,
            "product_tmpl_id": self.template.id,
            "fixed_price": 90.0,
        })
        Item.create({
            "pricelist_id": self.pricelist_b.id,
            "product_tmpl_id": self.template.id,
            "compute_price": "percentage",
            "percent_price": 10.0,
        })
        Item.create({
            "pricelist_id": self.pricelist_b.id,
            "product_id": self.template.product_variant_id.id,
            "fixed_price": 70.0,
        })
        self.template.invalidate_recordset(["pricelist_line_ids"])
        self.assertEqual(self.template.pricelist_line_ids, fixed)

    def test_hides_default_pricelist(self):
        """Las reglas de la lista Predeterminado no aparecen en la tabla."""
        default = self.env["product.pricelist"].create({"name": "Predeterminado"})
        self.env["product.pricelist.item"].create({
            "pricelist_id": default.id,
            "product_tmpl_id": self.template.id,
            "fixed_price": 60.0,
        })
        self.template.invalidate_recordset(["pricelist_line_ids"])
        self.assertFalse(self.template.pricelist_line_ids)

    def test_shows_all_user_companies(self):
        """Con una sola empresa tildada se ven las listas de todas las del usuario."""
        company_a = self.env["res.company"].create({"name": "Empresa A"})
        company_b = self.env["res.company"].create({"name": "Empresa B"})
        user = self.env["res.users"].create({
            "name": "Usuario multiempresa",
            "login": "pricelist_lines_user",
            "company_id": company_a.id,
            "company_ids": [(6, 0, (company_a | company_b).ids)],
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        Item = self.env["product.pricelist.item"]
        for company in company_a | company_b:
            pricelist = self.env["product.pricelist"].create({
                "name": "Lista %s" % company.name,
                "company_id": company.id,
            })
            Item.create({
                "pricelist_id": pricelist.id,
                "product_tmpl_id": self.template.id,
                "fixed_price": 50.0,
            })
        template = self.template.with_user(user).with_context(
            allowed_company_ids=[company_a.id])
        self.assertEqual(
            template.pricelist_line_ids.mapped("company_id"), company_a | company_b)

    def test_delete_from_form_removes_rule(self):
        """Borrar la fila elimina la regla de la lista."""
        self.template.write({"pricelist_line_ids": [
            (0, 0, {"pricelist_id": self.pricelist_a.id, "fixed_price": 80.0}),
        ]})
        item = self.template.pricelist_line_ids
        self.template.write({"pricelist_line_ids": [(2, item.id)]})
        self.assertFalse(item.exists())
