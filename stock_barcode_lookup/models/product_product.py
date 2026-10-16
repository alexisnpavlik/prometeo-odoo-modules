# -*- coding: utf-8 -*-

import re

from odoo import api, models
from odoo.tools.misc import format_amount


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _barcode_lookup_price(self):
        """Precio de venta formateado con la moneda del producto."""
        return format_amount(self.env, self.lst_price, self.currency_id or self.env.company.currency_id)

    def _barcode_lookup_data(self, code):
        """Datos que muestra la tarjeta de resultado de la app Escáner."""
        template = self.product_tmpl_id
        return {
            "found": True,
            "code": code or self.barcode or self.default_code or "",
            "product_id": self.id,
            "template_id": template.id,
            "name": self.display_name,
            "price": self._barcode_lookup_price(),
            "qty_available": "%g" % self.qty_available,
            "uom": self.uom_id.name,
            "vendor": template.seller_ids[:1].partner_id.name or "",
            "image_url": "/web/image/product.product/%s/image_512" % self.id,
            "can_replenish": bool(self.is_storable),
        }

    @api.model
    def barcode_lookup(self, code):
        """Busca un producto por código de barras (o referencia) exacto para la app Escáner."""
        code = (code or "").strip()
        if not code:
            return {"found": False, "code": code, "is_code": True}
        product = self.search([("barcode", "=", code)], limit=1) or self.search(
            [("default_code", "=", code)], limit=1
        )
        if not product:
            # Sin letras ni espacios se trata como código; si no, como nombre (para "Crear producto")
            is_code = not re.search(r"[^\W\d_]|\s", code)
            return {"found": False, "code": code, "is_code": is_code}
        return product._barcode_lookup_data(code)

    @api.model
    def barcode_lookup_product(self, product_id):
        """Tarjeta de resultado para un producto elegido de la lista de búsqueda."""
        product = self.browse(product_id).exists()
        if not product:
            return {"found": False, "code": "", "is_code": True}
        return product._barcode_lookup_data(False)

    @api.model
    def barcode_lookup_search(self, term, limit=20):
        """Busca productos por nombre, código de barras o referencia (coincidencia parcial)."""
        term = (term or "").strip()
        if len(term) < 2:
            return []
        domain = ["|", "|", ("name", "ilike", term), ("barcode", "ilike", term), ("default_code", "ilike", term)]
        products = self.search(domain, limit=limit, order="name")
        return [
            {
                "product_id": product.id,
                "name": product.display_name,
                "code": product.barcode or product.default_code or "",
                "price": product._barcode_lookup_price(),
                "image_url": "/web/image/product.product/%s/image_128" % product.id,
            }
            for product in products
        ]
