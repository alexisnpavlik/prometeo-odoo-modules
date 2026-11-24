from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # El precio de venta ya tiene seguimiento en Odoo; el costo no.
    standard_price = fields.Float(tracking=True)
