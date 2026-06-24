from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    surcharge_pc = fields.Float(
        string="Porcentaje de recargo",
        default=20.0,
        help="Porcentaje aplicado al tocar el botón Recargo en el POS.",
    )
    surcharge_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto de recargo",
        domain="[('available_in_pos', '=', True)]",
        help="Producto usado como línea de recargo en el pedido del POS.",
    )
