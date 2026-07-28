# -*- coding: utf-8 -*-
from odoo import _, fields, models


class CawStatementWizard(models.TransientModel):
    _name = "caw.statement.wizard"
    _description = "Resumen de cuenta corriente a una fecha"

    account_id = fields.Many2one(
        comodel_name="caw.account",
        string="Cuenta corriente",
        required=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(related="account_id.partner_id", readonly=True)
    currency_id = fields.Many2one(related="account_id.currency_id", readonly=True)
    date_to = fields.Date(
        string="Saldo a la fecha",
        required=True,
        default=fields.Date.context_today,
    )

    def _caw_statement_data(self):
        """Arma los datos del resumen: retiros, cuotas, pagos y saldo a la fecha."""
        self.ensure_one()
        account = self.account_id
        withdrawals = self.env["caw.withdrawal"].search(
            [
                ("account_id", "=", account.id),
                ("date", "<=", self.date_to),
                ("state", "not in", ("draft", "cancel")),
            ],
            order="date asc, name asc",
        )
        payments = self.env["caw.payment"].search(
            [
                ("account_id", "=", account.id),
                ("date", "<=", self.date_to),
                ("state", "=", "posted"),
            ],
            order="date asc, name asc",
        )
        installments = withdrawals.mapped("installment_ids")
        total_withdrawn = sum(withdrawals.mapped("amount_total"))
        total_paid = sum(
            installments.mapped("allocation_ids")
            .filtered(lambda a: a.date <= self.date_to and a.payment_id.state == "posted")
            .mapped("amount")
        )
        return {
            "account": account,
            "withdrawals": withdrawals,
            "installments": installments,
            "payments": payments,
            "total_withdrawn": total_withdrawn,
            "total_paid": total_paid,
            "balance": total_withdrawn - total_paid,
            "overdue": account.overdue_balance,
            "credit": account.credit_balance,
            "date_to": self.date_to,
        }

    def action_print(self):
        """Genera el PDF del resumen de cuenta."""
        self.ensure_one()
        return self.env.ref(
            "checking_account_withdrawals.action_report_caw_statement"
        ).report_action(self)
