# -*- coding: utf-8 -*-

from odoo import models
from odoo.osv import expression


class PosConfig(models.Model):
    _inherit = "pos.config"

    def _get_available_product_domain(self):
        """Si el POS limita categorías, carga igual los packs y sus productos: un pack sin
        categoría (o con componentes de otra) no se cargaría y no aparecería."""
        domain = super()._get_available_product_domain()
        if not (self.limit_categories and self.iface_available_categ_ids):
            return domain
        category_leaf = ("pos_categ_ids", "in", self._get_available_categories().ids)
        if category_leaf not in domain:
            return domain
        component_ids = (
            self.env["pos.promotion.pack.line"]
            .sudo()
            .search([("pack_tmpl_id.active", "=", True)])
            .product_id.ids
        )
        index = domain.index(category_leaf)
        widened = expression.OR([
            [category_leaf],
            [("product_tmpl_id.is_promotion_pack", "=", True)],
            [("id", "in", component_ids)],
        ])
        return domain[:index] + widened + domain[index + 1:]
