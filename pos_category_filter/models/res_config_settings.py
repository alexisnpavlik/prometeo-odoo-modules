# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_category_filter_mode = fields.Selection(related="pos_config_id.category_filter_mode", readonly=False)
    pos_category_filter_ids = fields.Many2many(related="pos_config_id.category_filter_ids", readonly=False)
