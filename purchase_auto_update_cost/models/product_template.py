from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # El precio de venta ya tiene seguimiento en Odoo; el costo no.
    standard_price = fields.Float(tracking=True)


class ProductProduct(models.Model):
    _inherit = "product.product"

    # Algunas pantallas (p. ej. desde la línea de compra) abren la variante, que
    # tiene su propio historial: el costo se sigue también acá.
    standard_price = fields.Float(tracking=True)
