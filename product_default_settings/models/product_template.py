from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    available_in_pos = fields.Boolean(default=True)
