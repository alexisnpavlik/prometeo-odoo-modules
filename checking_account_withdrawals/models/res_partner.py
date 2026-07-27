# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    caw_enabled = fields.Boolean(
        string="Habilitado para cuenta corriente",
        tracking=True,
        help="Si está marcado, este contacto puede retirar mercadería a cuenta corriente. "
             "Al marcarlo se crea automáticamente su cuenta en la compañía activa.",
    )
    caw_account_ids = fields.One2many(
        comodel_name="caw.account",
        inverse_name="partner_id",
        string="Cuentas corrientes",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Crea la cuenta corriente de los contactos que nacen habilitados."""
        partners = super().create(vals_list)
        partners.filtered("caw_enabled")._caw_ensure_account()
        return partners

    def write(self, vals):
        """Crea la cuenta corriente al habilitar el contacto."""
        res = super().write(vals)
        if vals.get("caw_enabled"):
            self._caw_ensure_account()
        return res

    def _caw_ensure_account(self):
        """Garantiza que exista la cuenta del contacto en la compañía activa."""
        account_model = self.env["caw.account"].sudo()
        for partner in self:
            account_model._get_or_create(partner, self.env.company)
