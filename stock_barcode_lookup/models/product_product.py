# -*- coding: utf-8 -*-

from odoo import api, models
from odoo.tools.misc import format_amount


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def barcode_lookup(self, code):
        """Busca un producto por código de barras (o referencia) para la app Escáner."""
        code = (code or "").strip()
        if not code:
            return {"found": False, "code": code}
        product = self.search([("barcode", "=", code)], limit=1) or self.search(
            [("default_code", "=", code)], limit=1
        )
        if not product:
            return {"found": False, "code": code}
        template = product.product_tmpl_id
        return {
            "found": True,
            "code": code,
            "product_id": product.id,
            "template_id": template.id,
            "name": product.display_name,
            "price": format_amount(self.env, product.lst_price, product.currency_id or self.env.company.currency_id),
            "qty_available": "%g" % product.qty_available,
            "uom": product.uom_id.name,
            "vendor": template.seller_ids[:1].partner_id.name or "",
            "image_url": "/web/image/product.product/%s/image_512" % product.id,
            "can_replenish": bool(product.is_storable),
        }
