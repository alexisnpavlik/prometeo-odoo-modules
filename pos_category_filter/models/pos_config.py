# -*- coding: utf-8 -*-

from odoo import fields, models
from odoo.osv import expression


class PosConfig(models.Model):
    _inherit = "pos.config"

    category_filter_mode = fields.Selection(
        [
            ("all", "Todos"),
            ("include", "Solo estas categorías"),
            ("exclude", "Todas menos estas"),
        ],
        string="Productos",
        default="all",
        required=True,
        help="Qué productos vende esta caja según su categoría de producto. "
        "Elegir una categoría incluye todas sus subcategorías.",
    )
    category_filter_ids = fields.Many2many(
        "product.category",
        "pos_config_category_filter_rel",
        "config_id",
        "categ_id",
        string="Categorías",
    )

    def _get_category_filter_domain(self):
        """Dominio de product.product según el filtro de categorías de la caja; vacío si no filtra."""
        self.ensure_one()
        if self.category_filter_mode == "all" or not self.category_filter_ids:
            return []
        leaf = [("categ_id", "child_of", self.category_filter_ids.ids)]
        if self.category_filter_mode == "include":
            return leaf
        return ["!"] + leaf

    def _get_promotion_pack_domain(self):
        """Packs de pos_promotions y sus componentes, que se cargan siempre; vacío si el módulo no está."""
        if "is_promotion_pack" not in self.env["product.template"]._fields:
            return []
        component_ids = (
            self.env["pos.promotion.pack.line"]
            .sudo()
            .search([("pack_tmpl_id.active", "=", True)])
            .product_id.ids
        )
        return expression.OR([
            [("product_tmpl_id.is_promotion_pack", "=", True)],
            [("id", "in", component_ids)],
        ])

    def _get_available_product_domain(self):
        """Agrega a la carga del POS el filtro por categoría de producto de la caja."""
        domain = super()._get_available_product_domain()
        category_domain = self._get_category_filter_domain()
        if not category_domain:
            return domain
        pack_domain = self._get_promotion_pack_domain()
        if pack_domain:
            category_domain = expression.OR([category_domain, pack_domain])
        return expression.AND([domain, category_domain])
