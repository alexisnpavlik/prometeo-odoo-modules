# -*- coding: utf-8 -*-
from odoo import fields, models


class CcaInstallment(models.Model):
    _name = "cca.installment"
    _description = "Cuota de retiro de cliente"

    withdrawal_id = fields.Many2one("cca.withdrawal", required=True, ondelete="cascade")
    account_id = fields.Many2one(related="withdrawal_id.account_id", store=True)
    partner_id = fields.Many2one("res.partner")
    company_id = fields.Many2one("res.company")
    currency_id = fields.Many2one("res.currency")
    sequence = fields.Integer()
    date_due = fields.Date()
    amount = fields.Monetary(currency_field="currency_id")
    amount_residual = fields.Monetary(currency_field="currency_id")
    state = fields.Selection([("pending", "Pendiente")])
    allocation_ids = fields.One2many("cca.allocation", "installment_id")
