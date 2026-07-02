from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_enable_sales_advisor = fields.Boolean(
        related="pos_config_id.enable_sales_advisor",
        readonly=False,
    )
    pos_require_sales_advisor = fields.Boolean(
        related="pos_config_id.require_sales_advisor",
        readonly=False,
    )
