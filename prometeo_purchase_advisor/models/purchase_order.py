# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    suggestion_id = fields.Many2one(
        "prometeo.purchase.suggestion", string="Sugerencia de compra",
        readonly=True, index=True, ondelete="set null",
        help="Sugerencia del recomendador que originó esta orden.",
    )
