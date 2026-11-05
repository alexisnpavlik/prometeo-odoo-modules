# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import AccessError


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def cca_pos_partner_summary(self, partner_id, company_id):
        """Saldo de cuenta corriente de un cliente para mostrar en el POS.

        Lee la cuenta activa con sudo (el cajero no tiene group_cca_user) y no la crea.
        Requiere grupo de usuario POS y que la compañía sea una de las del usuario.
        """
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("Solo los usuarios del punto de venta pueden consultar la cuenta corriente."))
        if company_id not in self.env.user.company_ids.ids:
            raise AccessError(_("No tenés acceso a esa compañía."))
        account = self.env["cca.account"].sudo().search([
            ("partner_id", "=", partner_id),
            ("company_id", "=", company_id),
        ], limit=1)
        if not account:
            return {
                "has_account": False,
                "balance": 0.0,
                "overdue": 0.0,
                "credit": 0.0,
                "credit_limit": 0.0,
                "limit_mode": "none",
            }
        currency = account.currency_id
        return {
            "has_account": True,
            "balance": currency.round(account.balance),
            "overdue": currency.round(account.overdue_balance),
            "credit": currency.round(account.credit_balance),
            "credit_limit": currency.round(account.credit_limit),
            "limit_mode": account.limit_mode,
        }
