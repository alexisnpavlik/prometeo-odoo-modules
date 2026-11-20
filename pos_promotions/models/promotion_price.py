# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PromotionPrice(models.Model):
    _name = "pos.promotion.price"
    _description = "Precio de una promoción en una lista"
    _order = "pricelist_id"

    pack_tmpl_id = fields.Many2one("product.template", string="Promoción", required=True, ondelete="cascade", index=True)
    pricelist_id = fields.Many2one("product.pricelist", string="Lista de precios", required=True, ondelete="cascade")
    price = fields.Float("Precio de la promoción", required=True, digits="Product Price")
    currency_id = fields.Many2one(related="pricelist_id.currency_id")

    _sql_constraints = [
        ("pack_pricelist_unique", "unique(pack_tmpl_id, pricelist_id)", "Cada lista puede tener un solo precio por promoción."),
    ]

    @api.constrains("pricelist_id", "price")
    def _check_price(self):
        """El precio por lista va en una lista de la promoción y no puede ser 1 o menos.
        Se guarda acá y no como regla de la lista para no pisar el precio de la sucursal."""
        for record in self:
            if record.price <= 1:
                raise ValidationError(_("Poné el precio de la promoción en %s (no puede ser 1 o menos).", record.pricelist_id.display_name))
            if record.pricelist_id not in record.pack_tmpl_id.sudo().promotion_pricelist_ids:
                raise ValidationError(
                    _("%s no está en las listas de la promoción: agregala primero.", record.pricelist_id.display_name)
                )
