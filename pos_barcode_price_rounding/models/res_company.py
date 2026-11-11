from odoo import api, fields, models

ROUNDING_METHODS = [
    ("nearest", "Al más cercano"),
    ("up", "Hacia arriba"),
    ("down", "Hacia abajo"),
]


class ResCompany(models.Model):
    _inherit = "res.company"

    barcode_price_rounding_enabled = fields.Boolean(
        string="Redondear precio de código de barra", default=True
    )
    barcode_price_rounding_step = fields.Integer(
        string="Múltiplo de redondeo", default=100
    )
    barcode_price_rounding_method = fields.Selection(
        ROUNDING_METHODS, string="Modo de redondeo", default="nearest", required=True
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Expone la configuración de redondeo al frontend del POS."""
        res = super()._load_pos_data_fields(config_id)
        return res + [
            "barcode_price_rounding_enabled",
            "barcode_price_rounding_step",
            "barcode_price_rounding_method",
        ]
