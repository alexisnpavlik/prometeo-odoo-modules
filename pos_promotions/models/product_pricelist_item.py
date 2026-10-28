# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Clave de contexto que pone la acción Promociones (product.pricelist.action_open_promotions).
PROMOTIONS_CONTEXT_KEY = "pos_promotions"


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    promotion_regular_price = fields.Monetary(
        "Precio antes del descuento", compute="_compute_promotion_prices", currency_field="currency_id"
    )
    promotion_price = fields.Monetary(
        "Precio después del descuento", compute="_compute_promotion_prices", currency_field="currency_id"
    )
    promotion_saving = fields.Monetary("Ahorro", compute="_compute_promotion_prices", currency_field="currency_id")

    @api.depends(
        "applied_on", "product_id", "product_tmpl_id", "compute_price", "fixed_price",
        "percent_price", "price_discount", "price_surcharge", "price_round", "base", "base_pricelist_id",
    )
    def _compute_promotion_prices(self):
        """Informativo: precio de venta del producto, precio con la regla y la diferencia.
        Solo en reglas de un producto; en categorías cada producto tiene su precio y queda en cero."""
        today = fields.Datetime.now()
        for item in self:
            product = item.product_id if item.applied_on == "0_product_variant" else item.product_tmpl_id
            if item.applied_on not in ("0_product_variant", "1_product") or not product:
                item.promotion_regular_price = item.promotion_price = item.promotion_saving = 0.0
                continue
            regular = product.list_price if product._name == "product.template" else product.lst_price
            price = item._compute_price(product, max(item.min_quantity, 1.0), product.uom_id, today, item.currency_id)
            item.promotion_regular_price = regular
            item.promotion_price = price
            item.promotion_saving = regular - price

    @api.constrains("applied_on", "product_tmpl_id", "product_id", "categ_id")
    def _check_promotion_has_target(self):
        """Desde Promociones, una regla sin producto ni categoría no se guarda: quedaría para
        todo el catálogo (con precio fijo $0, todo gratis en el POS)."""
        if not self.env.context.get(PROMOTIONS_CONTEXT_KEY):
            return
        for item in self:
            if item.applied_on == "3_global":
                raise ValidationError(_("Elegí un producto o una categoría para la promoción."))
