from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    barcode_price_rounding_enabled = fields.Boolean(
        related="company_id.barcode_price_rounding_enabled", readonly=False
    )
    barcode_price_rounding_step = fields.Integer(
        related="company_id.barcode_price_rounding_step", readonly=False
    )
    barcode_price_rounding_method = fields.Selection(
        related="company_id.barcode_price_rounding_method", readonly=False
    )
