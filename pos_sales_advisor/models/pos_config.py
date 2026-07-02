from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    enable_sales_advisor = fields.Boolean(
        string="Usar asesores de venta",
        default=False,
        help="Si está activo, la pantalla de pago de esta caja muestra el botón de asesor de venta.",
    )
    require_sales_advisor = fields.Boolean(
        string="Requerir asesor de venta",
        default=False,
        help="Si está activo, no se puede validar el pago sin seleccionar un asesor de venta.",
    )
