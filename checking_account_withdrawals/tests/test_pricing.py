# -*- coding: utf-8 -*-
from odoo.tests import Form, tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawPricing(CawCommon):
    """El precio de la línea sale de la lista configurada para la sucursal."""

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.product.list_price = 1000.0

    def _pricelist(self, name, items):
        """Lista de precios de la compañía con los items indicados."""
        return self.env["product.pricelist"].create({
            "name": name,
            "company_id": self.company.id,
            "currency_id": self.company.currency_id.id,
            "item_ids": [(0, 0, item) for item in items],
        })

    def _line(self, withdrawal, qty=1.0):
        """Agrega una línea por la UI para que corran los onchange."""
        with Form(withdrawal) as form:
            with form.line_ids.new() as line:
                line.product_id = self.product
                line.quantity = qty
        return withdrawal.line_ids[-1]

    def _draft(self):
        """Retiro en borrador vacío, con la lista que resuelva la compañía."""
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
        })

    def test_without_pricelist_uses_list_price(self):
        """Sin lista configurada se mantiene el precio base del producto."""
        self.company.caw_pricelist_id = False
        withdrawal = self._draft()
        self.assertFalse(withdrawal.pricelist_id)
        self.assertEqual(self._line(withdrawal).price_unit, 1000.0)

    def test_fixed_rule_wins_over_list_price(self):
        """Una regla de precio fijo para el producto reemplaza al precio base."""
        self.company.caw_pricelist_id = self._pricelist("Lista Sucursal Test", [{
            "applied_on": "1_product",
            "product_tmpl_id": self.product.product_tmpl_id.id,
            "compute_price": "fixed",
            "fixed_price": 750.0,
        }])
        self.assertEqual(self._line(self._draft()).price_unit, 750.0)

    def test_percentage_rule_applies_discount(self):
        """Una lista de descuento global (20%) cotiza el retiro con ese descuento."""
        self.company.caw_pricelist_id = self._pricelist("Lista Descuento 20", [{
            "applied_on": "3_global",
            "compute_price": "percentage",
            "percent_price": 20.0,
            "base": "list_price",
        }])
        self.assertEqual(self._line(self._draft()).price_unit, 800.0)

    def test_quantity_rule_recalculates_price(self):
        """Cambiar la cantidad reevalúa las reglas por cantidad mínima."""
        self.company.caw_pricelist_id = self._pricelist("Lista Mayorista Test", [
            {
                "applied_on": "1_product",
                "product_tmpl_id": self.product.product_tmpl_id.id,
                "compute_price": "fixed",
                "fixed_price": 900.0,
                "min_quantity": 1,
            },
            {
                "applied_on": "1_product",
                "product_tmpl_id": self.product.product_tmpl_id.id,
                "compute_price": "fixed",
                "fixed_price": 600.0,
                "min_quantity": 10,
            },
        ])
        withdrawal = self._draft()
        self.assertEqual(self._line(withdrawal, qty=1.0).price_unit, 900.0)
        self.assertEqual(self._line(withdrawal, qty=12.0).price_unit, 600.0)

    def test_withdrawal_freezes_company_pricelist(self):
        """El retiro guarda la lista con la que se cotizó y no la sigue si cambia."""
        pricelist = self._pricelist("Lista Original", [{
            "applied_on": "1_product",
            "product_tmpl_id": self.product.product_tmpl_id.id,
            "compute_price": "fixed",
            "fixed_price": 750.0,
        }])
        self.company.caw_pricelist_id = pricelist
        withdrawal = self._draft()
        self.company.caw_pricelist_id = self._pricelist("Lista Nueva", [{
            "applied_on": "1_product",
            "product_tmpl_id": self.product.product_tmpl_id.id,
            "compute_price": "fixed",
            "fixed_price": 100.0,
        }])
        self.assertEqual(withdrawal.pricelist_id, pricelist)
        self.assertEqual(self._line(withdrawal).price_unit, 750.0)

    def test_manual_price_is_kept_on_confirm(self):
        """El precio que el Manager ajusta a mano no se pisa al confirmar."""
        self.company.caw_pricelist_id = self._pricelist("Lista Ajuste", [{
            "applied_on": "1_product",
            "product_tmpl_id": self.product.product_tmpl_id.id,
            "compute_price": "fixed",
            "fixed_price": 750.0,
        }])
        withdrawal = self._draft()
        line = self._line(withdrawal)
        line.price_unit = 500.0
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.line_ids.price_unit, 500.0)
        self.assertEqual(withdrawal.amount_total, 500.0)
