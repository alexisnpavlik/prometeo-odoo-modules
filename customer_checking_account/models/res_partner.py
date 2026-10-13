# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    cca_currency_id = fields.Many2one(
        comodel_name="res.currency",
        compute="_compute_cca_currency_id",
        help="Moneda de la compañía activa: res.partner no tiene currency_id sin el módulo account.",
    )
    cca_account_ids = fields.One2many("cca.account", "partner_id", string="Cuentas corrientes")
    cca_balance = fields.Monetary(
        string="Saldo cuenta corriente", compute="_compute_cca_amounts", currency_field="cca_currency_id"
    )
    cca_overdue_balance = fields.Monetary(
        string="Saldo vencido", compute="_compute_cca_amounts", currency_field="cca_currency_id"
    )
    cca_credit_balance = fields.Monetary(
        string="Saldo a favor", compute="_compute_cca_amounts", currency_field="cca_currency_id"
    )
    cca_withdrawal_count = fields.Integer(string="Retiros", compute="_compute_cca_amounts")

    @api.depends("cca_account_ids.balance", "cca_account_ids.overdue_balance", "cca_account_ids.credit_balance")
    def _compute_cca_amounts(self):
        """Suma los saldos de las cuentas del contacto visibles al usuario."""
        withdrawal_model = self.env["cca.withdrawal"]
        for partner in self:
            accounts = partner.cca_account_ids
            partner.cca_balance = sum(accounts.mapped("balance"))
            partner.cca_overdue_balance = sum(accounts.mapped("overdue_balance"))
            partner.cca_credit_balance = sum(accounts.mapped("credit_balance"))
            partner.cca_withdrawal_count = withdrawal_model.search_count(
                [("partner_id", "=", partner.id)]
            ) if partner.id else 0

    @api.depends_context("company")
    def _compute_cca_currency_id(self):
        """Moneda de la compañía activa para mostrar los saldos."""
        for partner in self:
            partner.cca_currency_id = self.env.company.currency_id

    def action_cca_open_withdrawals(self):
        """Smart button: retiros del contacto."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Retiros de %s", self.display_name),
            "res_model": "cca.withdrawal",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }
