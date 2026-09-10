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
    cvi_settlement_frequency = fields.Selection(
        related="company_id.cvi_settlement_frequency",
        readonly=False,
    )
    cvi_customer_mobile_required = fields.Boolean(
        related="company_id.cvi_customer_mobile_required",
        readonly=False,
    )
    cvi_customer_street_required = fields.Boolean(
        related="company_id.cvi_customer_street_required",
        readonly=False,
    )
    cvi_customer_city_required = fields.Boolean(
        related="company_id.cvi_customer_city_required",
        readonly=False,
    )
    cvi_customer_zip_required = fields.Boolean(
        related="company_id.cvi_customer_zip_required",
        readonly=False,
    )
    cvi_customer_dni_photos_required = fields.Boolean(
        related="company_id.cvi_customer_dni_photos_required",
        readonly=False,
    )
