# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class ResPartner(models.Model):
    _inherit = "res.partner"

    caw_enabled = fields.Boolean(
        string="Habilitado para cuenta corriente",
        tracking=True,
        help="Si está marcado, este contacto puede retirar mercadería a cuenta corriente. "
             "Al marcarlo se crea automáticamente su cuenta en la compañía activa.\n"
             "Legible por cualquier usuario interno (el Operador necesita poder consultarlo "
             "para operar retiros); solo un Manager de Cuenta Corriente puede cambiarlo "
             "(ver write()).",
    )
    caw_account_ids = fields.One2many(
        comodel_name="caw.account",
        inverse_name="partner_id",
        string="Cuentas corrientes",
    )
    caw_balance = fields.Monetary(
        string="Saldo cuenta corriente",
        compute="_compute_caw_amounts",
        currency_field="currency_id",
    )
    caw_overdue_balance = fields.Monetary(
        string="Saldo vencido",
        compute="_compute_caw_amounts",
        currency_field="currency_id",
    )
    caw_credit_balance = fields.Monetary(
        string="Saldo a favor",
        compute="_compute_caw_amounts",
        currency_field="currency_id",
    )
    caw_withdrawal_count = fields.Integer(
        string="Retiros",
        compute="_compute_caw_amounts",
    )

    @api.depends(
        "caw_account_ids.balance",
        "caw_account_ids.overdue_balance",
        "caw_account_ids.credit_balance",
    )
    def _compute_caw_amounts(self):
        """Agrega los saldos de todas las cuentas del contacto visibles al usuario."""
        withdrawal_model = self.env["caw.withdrawal"]
        for partner in self:
            accounts = partner.caw_account_ids
            partner.caw_balance = sum(accounts.mapped("balance"))
            partner.caw_overdue_balance = sum(accounts.mapped("overdue_balance"))
            partner.caw_credit_balance = sum(accounts.mapped("credit_balance"))
            partner.caw_withdrawal_count = withdrawal_model.search_count([
                ("partner_id", "=", partner.id),
            ]) if partner.id else 0

    def action_caw_open_withdrawals(self):
        """Botón inteligente: abre los retiros del contacto."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Retiros de %s", self.display_name),
            "res_model": "caw.withdrawal",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Crea la cuenta corriente de los contactos que nacen habilitados."""
        partners = super().create(vals_list)
        partners.filtered("caw_enabled")._caw_ensure_account()
        return partners

    def write(self, vals):
        """Crea la cuenta corriente al habilitar el contacto.

        `caw_enabled` no lleva `groups=` (el Operador necesita poder LEERLO para operar
        retiros sobre un contacto ya habilitado, y el domain de `caw.withdrawal.partner_id`
        también necesita leerlo libremente al hacer `search()`). En cambio, la escritura
        se restringe acá: solo un Manager de Cuenta Corriente puede cambiar el valor.
        """
        if "caw_enabled" in vals and not self.env.user.has_group(
            "checking_account_withdrawals.group_cc_manager"
        ):
            raise AccessError(_(
                "Solo un Manager de Cuenta Corriente puede habilitar o deshabilitar "
                "la cuenta corriente de un contacto."
            ))
        res = super().write(vals)
        if vals.get("caw_enabled"):
            self._caw_ensure_account()
        return res

    def _caw_ensure_account(self):
        """Garantiza que exista la cuenta del contacto en la compañía activa."""
        account_model = self.env["caw.account"].sudo()
        for partner in self:
            account_model._get_or_create(partner, self.env.company)
