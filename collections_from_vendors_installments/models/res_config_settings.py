# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cvi_default_installments = fields.Integer(
        related="company_id.cvi_default_installments",
        readonly=False,
    )
    cvi_overdue_days = fields.Integer(
        related="company_id.cvi_overdue_days",
        readonly=False,
    )
    cvi_allowed_frequencies = fields.Selection(
        related="company_id.cvi_allowed_frequencies",
        readonly=False,
    )
