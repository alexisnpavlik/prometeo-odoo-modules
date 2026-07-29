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
    withdrawal_ids = fields.One2many(
        comodel_name="caw.withdrawal",
        inverse_name="account_id",
        string="Retiros",
    )
    payment_ids = fields.One2many(
        comodel_name="caw.payment",
        inverse_name="account_id",
        string="Pagos",
    )
    installment_ids = fields.One2many(
        comodel_name="caw.installment",
        inverse_name="account_id",
        string="Cuotas",
    )
    balance = fields.Monetary(
        string="Saldo",
        compute="_compute_balances",
        store=True,
        currency_field="currency_id",
    )
    overdue_balance = fields.Monetary(
        string="Saldo vencido",
        compute="_compute_balances",
        store=True,
        currency_field="currency_id",
    )
    credit_balance = fields.Monetary(
        string="Saldo a favor",
        compute="_compute_credit_balance",
        store=True,
        currency_field="currency_id",
    )

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

    @api.depends(
        "installment_ids.amount_residual",
        "installment_ids.state",
        "installment_ids.date_due",
        "installment_ids.withdrawal_id.state",
    )
    def _compute_balances(self):
        """Saldo y vencido: residuales de cuotas de retiros vivos (ni borrador ni cancelados)."""
        today = fields.Date.context_today(self)
        for account in self:
            open_installments = account.installment_ids.filtered(
                lambda i: i.withdrawal_id.state not in ("draft", "cancel")
            )
            account.balance = sum(open_installments.mapped("amount_residual"))
            account.overdue_balance = sum(
                open_installments
                .filtered(lambda i: i.date_due and i.date_due < today and i.amount_residual > 0)
                .mapped("amount_residual")
            )

    @api.depends("payment_ids.amount_unallocated", "payment_ids.state")
    def _compute_credit_balance(self):
        """Saldo a favor: remanente no imputado de los pagos publicados."""
        for account in self:
            account.credit_balance = sum(
                account.payment_ids
                .filtered(lambda p: p.state == "posted")
                .mapped("amount_unallocated")
            )

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
