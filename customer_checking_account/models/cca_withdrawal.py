# -*- coding: utf-8 -*-
from odoo import fields, models


class CcaWithdrawal(models.Model):
    _name = "cca.withdrawal"
    _description = "Retiro de cliente"

    account_id = fields.Many2one("cca.account", required=True, ondelete="restrict")
    state = fields.Selection([("draft", "Borrador"), ("cancel", "Cancelado")], default="draft")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
