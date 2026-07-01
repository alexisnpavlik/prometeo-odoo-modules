# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_pricelist_enforce = fields.Boolean(
        related="pos_config_id.pricelist_enforce",
        readonly=False,
        string="Forzar precio de lista al cobrar",
    )
    pos_pricelist_enforce_warn = fields.Boolean(
        related="pos_config_id.pricelist_enforce_warn",
        readonly=False,
        string="Avisar al corregir",
    )
