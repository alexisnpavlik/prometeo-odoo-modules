# -*- coding: utf-8 -*-

from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def find_product_by_barcode(self, barcode, config_id):
        """El fallback nativo busca el código en todo el catálogo: descarta lo que la caja no vende."""
        result = super().find_product_by_barcode(barcode, config_id)
        rows = result.get("product.product") or []
        if not rows:
            return result
        config = self.env["pos.config"].browse(config_id)
        found = self.env["product.product"].browse([row["id"] for row in rows])
        if config._filter_allowed_products(found) == found:
            return result
        return {"product.product": [], "product.packaging": []}
