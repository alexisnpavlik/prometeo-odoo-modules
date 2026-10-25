# -*- coding: utf-8 -*-

from odoo import _, api, models
from odoo.exceptions import ValidationError

# Clave de contexto que pone la acción Promociones (product.pricelist.action_open_promotions).
PROMOTIONS_CONTEXT_KEY = "web_menu_simplify_promotions"


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    @api.constrains("applied_on", "product_tmpl_id", "product_id", "categ_id")
    def _check_promotion_has_target(self):
        """Desde Promociones, una regla sin producto ni categoría no se guarda: quedaría para
        todo el catálogo (con precio fijo $0, todo gratis en el POS)."""
        if not self.env.context.get(PROMOTIONS_CONTEXT_KEY):
            return
        for item in self:
            if item.applied_on == "3_global":
                raise ValidationError(_("Elegí un producto o una categoría para la promoción."))
