# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CawConfirmWizard(models.TransientModel):
    _name = "caw.confirm.wizard"
    _description = "Confirmación de retiro: plan de cuotas y límite de crédito"

    withdrawal_id = fields.Many2one(
        comodel_name="caw.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(related="withdrawal_id.partner_id", readonly=True)
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    amount_total = fields.Monetary(
        related="withdrawal_id.amount_total",
        string="Total del retiro",
        readonly=True,
        currency_field="currency_id",
    )
    current_balance = fields.Monetary(
        string="Saldo actual",
        compute="_compute_account_info",
        currency_field="currency_id",
    )
    overdue_balance = fields.Monetary(
        string="Saldo vencido",
        compute="_compute_account_info",
        currency_field="currency_id",
    )
    plan_mode = fields.Selection(
        selection=[
            ("cash", "Contado en cuenta (una cuota)"),
            ("fixed", "Cuotas fijas"),
        ],
        string="Plan",
        default="cash",
        required=True,
    )
    installment_count = fields.Integer(string="Cantidad de cuotas", default=1, required=True)
    first_days = fields.Integer(string="Días al primer vencimiento", default=30, required=True)
    period = fields.Selection(
        selection=[("days", "Días"), ("weeks", "Semanas"), ("months", "Meses")],
        string="Periodicidad",
        default="months",
        required=True,
    )
    cutoff_day = fields.Integer(
        string="Día de corte",
        default=0,
        help="Día del mes al que se ajustan los vencimientos. 0 = sin día de corte.",
    )
    limit_warning = fields.Text(string="Advertencia de límite", compute="_compute_limit")
    limit_blocked = fields.Boolean(string="Bloqueado por límite", compute="_compute_limit")
    force_limit = fields.Boolean(
        string="Forzar sobre el límite",
        help="Solo un Manager puede forzar un retiro que supera el límite en modo bloqueo.",
    )

    @api.model
    def default_get(self, fields_list):
        """Propone el plan por defecto de la compañía del retiro."""
        values = super().default_get(fields_list)
        withdrawal = self.env["caw.withdrawal"].browse(values.get("withdrawal_id"))
        if withdrawal:
            company = withdrawal.company_id
            values.update({
                "installment_count": company.caw_installment_count or 1,
                "first_days": company.caw_installment_days or 30,
                "period": company.caw_installment_period or "months",
                "cutoff_day": company.caw_cutoff_day or 0,
                "plan_mode": "fixed" if (company.caw_installment_count or 1) > 1 else "cash",
            })
        return values

    @api.depends("withdrawal_id")
    def _compute_account_info(self):
        """Muestra el saldo del partner al momento de decidir el retiro."""
        for wizard in self:
            account = wizard.withdrawal_id.account_id.sudo()
            wizard.current_balance = account.balance
            wizard.overdue_balance = account.overdue_balance

    @api.depends("withdrawal_id", "amount_total")
    def _compute_limit(self):
        """Calcula el aviso de límite sin levantar excepción, para mostrarlo en el wizard."""
        for wizard in self:
            account = wizard.withdrawal_id.account_id.sudo()
            wizard.limit_warning = ""
            wizard.limit_blocked = False
            if account.limit_mode == "none" or not account.credit_limit:
                continue
            projected = account.balance + wizard.amount_total
            if wizard.currency_id.compare_amounts(projected, account.credit_limit) > 0:
                wizard.limit_warning = _(
                    "Saldo proyectado %(projected)s sobre un límite de %(limit)s.",
                    projected=projected,
                    limit=account.credit_limit,
                )
                wizard.limit_blocked = account.limit_mode == "block"

    @api.onchange("plan_mode")
    def _onchange_plan_mode(self):
        """En modo contado siempre hay una sola cuota."""
        for wizard in self:
            if wizard.plan_mode == "cash":
                wizard.installment_count = 1

    def action_confirm(self):
        """Confirma el retiro con el plan elegido en el wizard."""
        self.ensure_one()
        count = 1 if self.plan_mode == "cash" else self.installment_count
        if count < 1:
            raise UserError(_("La cantidad de cuotas debe ser al menos 1."))
        withdrawal = self.withdrawal_id
        force = self.force_limit and self.env.user.has_group(
            "checking_account_withdrawals.group_cc_manager"
        )
        withdrawal = withdrawal.with_context(
            caw_force_limit=force,
            caw_plan=(count, self.first_days, self.period, self.cutoff_day),
        )
        withdrawal.action_confirm()
        return {"type": "ir.actions.act_window_close"}
