# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PromotionPrice(models.Model):
    _name = "pos.promotion.price"
    _description = "Precio de una promoción en una sucursal"
    _order = "company_id"

    pack_tmpl_id = fields.Many2one("product.template", string="Promoción", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", string="Sucursal", required=True, ondelete="cascade")
    price = fields.Float("Precio de la promoción", required=True, digits="Product Price")
    currency_id = fields.Many2one(related="company_id.currency_id")

    _sql_constraints = [
        ("pack_company_unique", "unique(pack_tmpl_id, company_id)", "Cada sucursal puede tener un solo precio por promoción."),
    ]

    @api.constrains("price")
    def _check_price(self):
        """No puede ser 1 o menos. Que la sucursal sea de la promoción lo valida la promoción
        (al crearla, los precios se guardan antes que sus sucursales). Se guarda acá y no
        como regla de la lista para no pisar el precio de la sucursal."""
        for record in self:
            if record.price <= 1:
                raise ValidationError(_("Poné el precio de la promoción en %s (no puede ser 1 o menos).", record.company_id.name))
