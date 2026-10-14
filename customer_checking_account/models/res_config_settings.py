# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cca_currency_id = fields.Many2one(related="company_id.currency_id")
    cca_default_credit_limit = fields.Monetary(
        related="company_id.cca_default_credit_limit", readonly=False, currency_field="cca_currency_id"
    )
    cca_default_limit_mode = fields.Selection(
        related="company_id.cca_default_limit_mode", readonly=False
    )
    cca_picking_type_id = fields.Many2one(related="company_id.cca_picking_type_id", readonly=False)
