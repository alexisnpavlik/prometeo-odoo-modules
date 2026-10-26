# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PromotionPackLine(models.Model):
    _name = "pos.promotion.pack.line"
    _inherit = ["pos.load.mixin"]
    _description = "Componente de pack de promoción"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    pack_tmpl_id = fields.Many2one("product.template", string="Pack", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        domain=[("type", "!=", "combo"), ("available_in_pos", "=", True)],
    )
    quantity = fields.Integer(string="Cantidad", default=1, required=True)
    lst_price = fields.Float(related="product_id.lst_price", string="Precio unitario")
    currency_id = fields.Many2one(related="product_id.currency_id")

    @api.model
    def _load_pos_data_domain(self, data):
        """El POS detecta los packs activos: carga sus productos y cantidades."""
        return [("pack_tmpl_id.active", "=", True), ("pack_tmpl_id.available_in_pos", "=", True)]

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ["id", "pack_tmpl_id", "product_id", "quantity"]

    @api.depends("product_id", "quantity")
    def _compute_display_name(self):
        """'2 × Coca-Cola' para la lista de packs."""
        for line in self:
            line.display_name = f"{line.quantity} × {line.product_id.display_name or ''}"

    @api.constrains("quantity")
    def _check_quantity(self):
        """Cada componente lleva al menos una unidad."""
        if any(line.quantity < 1 for line in self):
            raise ValidationError(_("La cantidad de cada producto del pack tiene que ser 1 o más."))

    @api.constrains("product_id")
    def _check_product_in_pos(self):
        """El POS solo carga los combos cuyos productos están disponibles en el POS."""
        for line in self:
            if not line.product_id.available_in_pos:
                raise ValidationError(
                    _("%s no está disponible en el Punto de venta: no se puede usar en un pack.", line.product_id.display_name)
                )
