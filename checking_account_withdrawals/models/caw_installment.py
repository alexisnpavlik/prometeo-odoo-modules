# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("pending", "Pendiente"),
    ("partial", "Parcial"),
    ("paid", "Pagada"),
    ("overdue", "Vencida"),
]


class CawInstallment(models.Model):
    _name = "caw.installment"
    _description = "Cuota de retiro de cuenta corriente"
    _order = "date_due, withdrawal_id, sequence, id"

    withdrawal_id = fields.Many2one(
        comodel_name="caw.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
        index=True,
    )
    account_id = fields.Many2one(
        related="withdrawal_id.account_id",
        store=True,
        index=True,
        string="Cuenta corriente",
    )
    partner_id = fields.Many2one(
        related="withdrawal_id.partner_id",
        store=True,
        index=True,
        string="Contacto",
    )
    company_id = fields.Many2one(
        related="withdrawal_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    sequence = fields.Integer(string="Nº de cuota", default=1, required=True)
    allocation_ids = fields.One2many(
        comodel_name="caw.allocation",
        inverse_name="installment_id",
        string="Imputaciones",
    )
    date_due = fields.Date(string="Vencimiento", required=True, index=True)
    amount = fields.Monetary(
        string="Monto",
        required=True,
        currency_field="currency_id",
    )
    amount_allocated = fields.Monetary(
        string="Imputado",
        compute="_compute_amount_allocated",
        store=True,
        currency_field="currency_id",
    )
    amount_residual = fields.Monetary(
        string="Residual",
        compute="_compute_amount_residual",
        store=True,
        currency_field="currency_id",
    )
    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Estado",
        compute="_compute_state",
        store=True,
        index=True,
        default="pending",
    )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto de la cuota debe ser mayor a cero.",
        ),
    ]

    @api.depends("allocation_ids.amount", "allocation_ids.payment_id.state")
    def _compute_amount_allocated(self):
        """Suma de las imputaciones de pagos publicados sobre esta cuota."""
        for installment in self:
            installment.amount_allocated = sum(
                installment.allocation_ids
                .filtered(lambda a: a.payment_id.state == "posted")
                .mapped("amount")
            )

    @api.depends("amount", "amount_allocated")
    def _compute_amount_residual(self):
        """Residual de la cuota: monto menos lo imputado, nunca negativo."""
        for installment in self:
            residual = installment.amount - installment.amount_allocated
            installment.amount_residual = max(residual, 0.0)

    @api.depends("amount", "amount_allocated", "amount_residual", "date_due")
    def _compute_state(self):
        """Estado de la cuota. Solo es 'pagada' cuando el residual llega a cero."""
        today = fields.Date.context_today(self)
        for installment in self:
            rounding = installment.currency_id.rounding or 0.01
            if float_is_zero(installment.amount_residual, precision_rounding=rounding):
                installment.state = "paid"
            elif installment.date_due and installment.date_due < today:
                installment.state = "overdue"
            elif installment.amount_allocated > 0:
                installment.state = "partial"
            else:
                installment.state = "pending"

    @api.constrains("date_due", "withdrawal_id")
    def _check_due_date(self):
        """El vencimiento no puede ser anterior a la fecha del retiro."""
        for installment in self:
            withdrawal_date = installment.withdrawal_id.date
            if withdrawal_date and installment.date_due < withdrawal_date:
                raise ValidationError(_(
                    "El vencimiento de la cuota %(seq)s (%(due)s) es anterior a la fecha del retiro (%(date)s).",
                    seq=installment.sequence,
                    due=installment.date_due,
                    date=withdrawal_date,
                ))

    @api.constrains("amount", "withdrawal_id")
    def _check_total_matches_withdrawal(self):
        """Valida que la suma de cuotas del retiro iguale exactamente su total (CC-21).

        Es bloqueante y aplica tanto a la generación automática como a la carga manual.
        Odoo evalúa los constrains al final del create/write, así que crear las N cuotas
        en una sola llamada no lo dispara a mitad de camino.
        """
        for withdrawal in self.mapped("withdrawal_id"):
            total_installments = sum(withdrawal.installment_ids.mapped("amount"))
            if withdrawal.currency_id.compare_amounts(total_installments, withdrawal.amount_total) != 0:
                raise ValidationError(_(
                    "La suma de las cuotas (%(sum)s) no coincide con el total del retiro %(name)s (%(total)s).",
                    sum=total_installments,
                    name=withdrawal.name,
                    total=withdrawal.amount_total,
                ))

    @api.model
    def _cron_update_overdue(self):
        """Cron diario: recalcula el estado de las cuotas impagas ya vencidas.

        El estado es computado y almacenado, pero depende de la fecha de hoy, que no es
        un campo. Este cron fuerza el recálculo invalidando la caché de las candidatas.
        """
        today = fields.Date.context_today(self)
        candidates = self.search([
            ("date_due", "<", today),
            ("state", "in", ("pending", "partial")),
            ("withdrawal_id.state", "not in", ("draft", "cancel")),
        ])
        candidates.invalidate_recordset(["state"])
        candidates.modified(["date_due"])
        candidates._compute_state()
        candidates.mapped("account_id").invalidate_recordset(["overdue_balance"])
        _logger.info("Cron de vencidas: %s cuotas revisadas", len(candidates))
        return True
