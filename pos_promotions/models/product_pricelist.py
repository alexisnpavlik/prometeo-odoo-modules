# -*- coding: utf-8 -*-

from odoo import _, api, models

from .product_pricelist_item import PROMOTIONS_CONTEXT_KEY


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    @api.model
    def action_open_promotions(self):
        """Abre las reglas de la lista de precios principal como Promociones; las nuevas van a esa lista."""
        pricelist = self.search([], limit=1)
        return {
            "type": "ir.actions.act_window",
            "name": _("Promociones"),
            "res_model": "product.pricelist.item",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("pos_promotions.product_pricelist_item_promotions_list").id, "list"),
                (self.env.ref("pos_promotions.product_pricelist_item_promotions_form").id, "form"),
            ],
            "domain": [("pricelist_id", "=", pricelist.id)] if pricelist else [],
            "context": {PROMOTIONS_CONTEXT_KEY: True, "default_pricelist_id": pricelist.id},
        }
