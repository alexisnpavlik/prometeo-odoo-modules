# -*- coding: utf-8 -*-
from odoo import fields, models


class CcaPayment(models.Model):
    _name = "cca.payment"
    _description = "Pago de cliente"

    name = fields.Char()
    account_id = fields.Many2one("cca.account", required=True, ondelete="restrict")
    company_id = fields.Many2one(related="account_id.company_id", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date()
    amount = fields.Monetary(currency_field="currency_id")
    state = fields.Selection([("posted", "Registrado"), ("cancel", "Anulado")], default="posted")
    allocation_ids = fields.One2many("cca.allocation", "payment_id")
    amount_unallocated = fields.Monetary(currency_field="currency_id")
