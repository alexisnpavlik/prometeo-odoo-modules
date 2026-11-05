# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cca_pos_surcharge_percent = fields.Float(
        related="company_id.cca_pos_surcharge_percent", readonly=False
    )
    cca_pos_installment_count = fields.Integer(
        related="company_id.cca_pos_installment_count", readonly=False
    )
    cca_pos_first_due_days = fields.Integer(
        related="company_id.cca_pos_first_due_days", readonly=False
    )
    cca_pos_frequency = fields.Selection(
        related="company_id.cca_pos_frequency", readonly=False
    )
