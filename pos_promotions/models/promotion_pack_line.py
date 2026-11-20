# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PromotionPackLine(models.Model):
    _name = "pos.promotion.pack.line"
    _inherit = ["pos.load.mixin"]
    _description = "Producto de una promoción"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    pack_tmpl_id = fields.Many2one("product.template", string="Promoción", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        domain=[("type", "!=", "combo"), ("available_in_pos", "=", True)],
    )
    quantity = fields.Integer(string="Cantidad", default=1, required=True)
    lst_price = fields.Float(related="product_id.lst_price", string="Precio unitario")
    currency_id = fields.Many2one(related="product_id.currency_id")
    promotion_data_json = fields.Json(
        compute="_compute_promotion_data_json",
        help="Cómo se cobra la promoción en el POS: sucursales, tipo, % y vigencia.",
    )

    @api.depends(
        "pack_tmpl_id.promotion_company_ids", "pack_tmpl_id.promotion_price_mode",
        "pack_tmpl_id.promotion_discount_percent",
        "pack_tmpl_id.promotion_date_start", "pack_tmpl_id.promotion_date_end",
    )
    def _compute_promotion_data_json(self):
        """Ids crudos: el POS no carga las otras empresas, así que no sirve un Many2many."""
        for line in self:
            template = line.pack_tmpl_id.sudo()
            line.promotion_data_json = {
                "companies": template.promotion_company_ids.ids,
                "mode": template.promotion_price_mode,
                "percent": template.promotion_discount_percent,
                "date_start": fields.Date.to_string(template.promotion_date_start) or False,
                "date_end": fields.Date.to_string(template.promotion_date_end) or False,
            }

    @api.model
    def _load_pos_data_domain(self, data):
        """El POS carga las promociones activas de la sucursal (empresa) de esta caja."""
        config = self.env["pos.config"].browse(data["pos.config"]["data"][0]["id"])
        return [
            ("pack_tmpl_id.active", "=", True),
            ("pack_tmpl_id.available_in_pos", "=", True),
            ("pack_tmpl_id.promotion_company_ids", "in", config.company_id.ids),
            # Las vencidas no se cargan; las futuras sí (la sesión puede seguir abierta al empezar).
            "|", ("pack_tmpl_id.promotion_date_end", "=", False),
            ("pack_tmpl_id.promotion_date_end", ">=", fields.Date.context_today(self)),
        ]

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ["id", "pack_tmpl_id", "product_id", "quantity", "promotion_data_json"]

    @api.depends("product_id", "quantity")
    def _compute_display_name(self):
        """'2 × Coca-Cola' para la lista de packs."""
        for line in self:
            line.display_name = f"{line.quantity} × {line.product_id.display_name or ''}"

    @api.constrains("quantity")
    def _check_quantity(self):
        """Cada componente lleva al menos una unidad."""
        if any(line.quantity < 1 for line in self):
            raise ValidationError(_("La cantidad de cada producto de la promoción tiene que ser 1 o más."))

    @api.constrains("product_id")
    def _check_product_in_pos(self):
        """El POS solo carga los combos cuyos productos están disponibles en el POS."""
        for line in self:
            if not line.product_id.available_in_pos:
                raise ValidationError(
                    _("%s no está disponible en el Punto de venta: no se puede usar en una promoción.", line.product_id.display_name)
                )
