# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    caw_installment_count = fields.Integer(
        related="company_id.caw_installment_count",
        readonly=False,
    )
    caw_installment_days = fields.Integer(
        related="company_id.caw_installment_days",
        readonly=False,
    )
    caw_installment_period = fields.Selection(
        related="company_id.caw_installment_period",
        readonly=False,
    )
    caw_cutoff_day = fields.Integer(
        related="company_id.caw_cutoff_day",
        readonly=False,
    )
    caw_picking_type_id = fields.Many2one(
        related="company_id.caw_picking_type_id",
        readonly=False,
    )
    caw_pricelist_id = fields.Many2one(
        related="company_id.caw_pricelist_id",
        readonly=False,
    )
