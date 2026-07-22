# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    require_reason_order_deletion = fields.Boolean(
        related="pos_config_id.require_reason_order_deletion", readonly=False
    )
    require_reason_line_deletion = fields.Boolean(
        related="pos_config_id.require_reason_line_deletion", readonly=False
    )
    require_reason_qty_reduction = fields.Boolean(
        related="pos_config_id.require_reason_qty_reduction", readonly=False
    )
