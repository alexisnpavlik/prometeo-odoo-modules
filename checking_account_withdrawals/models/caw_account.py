# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class CawAccount(models.Model):
    _name = "caw.account"
    _description = "Cuenta corriente de retiros"
    _inherit = ["mail.thread"]
    _rec_name = "partner_id"
    _order = "partner_id, company_id"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contacto",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Moneda",
        readonly=True,
    )
    credit_limit = fields.Monetary(
        string="Límite de crédito",
        currency_field="currency_id",
        tracking=True,
        groups="checking_account_withdrawals.group_cc_manager",
    )
    limit_mode = fields.Selection(
        selection=[
            ("none", "Sin control"),
            ("warn", "Advertencia"),
            ("block", "Bloqueo"),
        ],
        string="Modo de límite",
        default="none",
        required=True,
        tracking=True,
        groups="checking_account_withdrawals.group_cc_manager",
        help="Advertencia: el Operador ve el aviso y puede continuar. "
             "Bloqueo: solo un Manager puede forzar el retiro.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "partner_company_uniq",
            "UNIQUE(partner_id, company_id)",
            "Ya existe una cuenta corriente para este contacto en esta compañía.",
        ),
    ]

    @api.constrains("credit_limit")
    def _check_credit_limit(self):
        """El límite de crédito no puede ser negativo."""
        for account in self:
            if account.credit_limit < 0:
                raise ValidationError(_("El límite de crédito no puede ser negativo."))

    @api.model
    def _get_or_create(self, partner, company):
        """Devuelve la cuenta del partner en la compañía, creándola si no existe."""
        account = self.with_context(active_test=False).search([
            ("partner_id", "=", partner.id),
            ("company_id", "=", company.id),
        ], limit=1)
        if account:
            if not account.active:
                account.active = True
            return account
        _logger.info("Creando cuenta corriente para %s en %s", partner.display_name, company.name)
        return self.create({
            "partner_id": partner.id,
            "company_id": company.id,
        })
