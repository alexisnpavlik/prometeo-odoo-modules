from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_enable_surcharge = fields.Boolean(
        related="pos_config_id.enable_surcharge",
        readonly=False,
        string="Botón de recargo",
    )
    pos_surcharge_pc = fields.Float(
        related="pos_config_id.surcharge_pc",
        readonly=False,
        string="Porcentaje de recargo",
    )
    pos_surcharge_product_id = fields.Many2one(
        related="pos_config_id.surcharge_product_id",
        readonly=False,
        string="Producto de recargo",
    )
