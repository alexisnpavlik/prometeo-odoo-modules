# -*- coding: utf-8 -*-

from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config_id):
        """El POS necesita saber qué productos son packs para mostrarlos sin categoría."""
        return super()._load_pos_data_fields(config_id) + ["is_promotion_pack"]

    def _add_missing_products(self, products, config_id, data):
        """Carga siempre el producto de cada promoción de la caja y sus componentes. El POS
        precarga una parte del catálogo; si quedan afuera, la promoción no se detecta (Odoo
        hace lo mismo con los combos y con los productos de órdenes ya cargadas)."""
        super()._add_missing_products(products, config_id, data)
        config = self.env["pos.config"].browse(config_id)
        Line = self.env["pos.promotion.pack.line"].sudo()
        lines = Line.search(Line._promotion_domain_for_config(config))
        wanted = set(lines.product_id.ids) | set(lines.pack_tmpl_id.product_variant_ids.ids)
        missing = wanted - {product["id"] for product in products}
        if missing:
            products.extend(self._load_product_with_domain([("id", "in", list(missing))], config_id))
