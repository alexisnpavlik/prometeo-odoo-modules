# -*- coding: utf-8 -*-
from odoo import fields, models


class CcaPayment(models.Model):
    _inherit = "cca.payment"

    pos_order_id = fields.Many2one(
        "pos.order", string="Pedido del POS", readonly=True, index=True, copy=False,
        help="Pedido del POS desde el que se cobró este pago.",
    )
