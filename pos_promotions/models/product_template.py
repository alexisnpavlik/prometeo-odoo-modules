# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_promotion_pack = fields.Boolean("Pack de promoción", copy=False)
    promotion_pack_line_ids = fields.One2many(
        "pos.promotion.pack.line", "pack_tmpl_id", string="Productos del pack", copy=True
    )
    promotion_pack_regular_price = fields.Float(
        "Precio normal", compute="_compute_promotion_pack_prices", digits="Product Price"
    )
    promotion_pack_saving = fields.Float(
        "Ahorro", compute="_compute_promotion_pack_prices", digits="Product Price"
    )

    @api.depends("list_price", "promotion_pack_line_ids.quantity", "promotion_pack_line_ids.product_id.lst_price")
    def _compute_promotion_pack_prices(self):
        """Precio de los productos sueltos y cuánto se ahorra con el pack."""
        for template in self:
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            template.promotion_pack_regular_price = regular
            template.promotion_pack_saving = regular - template.list_price if regular else 0.0

    @api.constrains("is_promotion_pack", "promotion_pack_line_ids")
    def _check_promotion_pack_lines(self):
        """Un pack necesita al menos un producto."""
        if any(template.is_promotion_pack and not template.promotion_pack_line_ids for template in self):
            raise ValidationError(_("Agregá al menos un producto al pack."))

    @api.model_create_multi
    def create(self, vals_list):
        """El pack es un producto sin stock propio: en el POS se venden sus productos."""
        for vals in vals_list:
            if vals.get("is_promotion_pack"):
                vals.update(type="consu", is_storable=False)
        return super().create(vals_list)
