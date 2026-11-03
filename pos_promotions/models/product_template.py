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
    promotion_pack_auto_price = fields.Float(
        "Último precio sugerido", copy=False, digits="Product Price",
        help="Suma que puso el formulario; si el precio sigue igual, se recalcula al cambiar productos.",
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

    @api.onchange("promotion_pack_line_ids")
    def _onchange_promotion_pack_lines_price(self):
        """Precio del pack por defecto = suma de sus productos. Se recalcula mientras siga
        en el default de Odoo (1), en la última suma sugerida o quede más caro que los
        productos sueltos; un precio con descuento puesto a mano se respeta."""
        for template in self.filtered("is_promotion_pack"):
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            price = template.list_price
            if regular and (price <= 1 or price == template.promotion_pack_auto_price or price > regular):
                template.list_price = template.promotion_pack_auto_price = regular

    @api.constrains("is_promotion_pack", "list_price", "promotion_pack_line_ids")
    def _check_promotion_pack_price(self):
        """El pack no puede salir más caro que sus productos sueltos ni costar 1 o menos."""
        for template in self.filtered("is_promotion_pack"):
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            if template.list_price <= 1:
                raise ValidationError(_("Poné el precio del pack (no puede ser 1 o menos)."))
            if regular and template.list_price > regular:
                raise ValidationError(
                    _("El pack no puede costar más que sus productos sueltos (%s).", round(regular, 2))
                )

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
