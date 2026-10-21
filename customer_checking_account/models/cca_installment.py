# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("pending", "Pendiente"),
    ("partial", "Parcial"),
    ("paid", "Pagada"),
    ("overdue", "Vencida"),
]


class CcaInstallment(models.Model):
    _name = "cca.installment"
    _description = "Cuota de retiro de cliente"
    _order = "date_due, withdrawal_id, sequence, id"

    withdrawal_id = fields.Many2one(
        comodel_name="cca.withdrawal",
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
    is_down_payment = fields.Boolean(
        string="Entrega inicial",
        help="Fila de la entrega inicial (número 0). Se paga al confirmar el retiro.",
    )
    label = fields.Char(string="Cuota", compute="_compute_label")
    allocation_ids = fields.One2many(
        comodel_name="cca.allocation",
        inverse_name="installment_id",
        string="Imputaciones",
    )
    date_due = fields.Date(string="Vencimiento", required=True, index=True)
    amount = fields.Monetary(
        string="Monto",
        required=True,
        currency_field="currency_id",
    )
    late_fee = fields.Monetary(
        string="Mora",
        currency_field="currency_id",
        readonly=True,
        help="Mora acumulada por días de atraso. La actualizan el cron diario y cada pago.",
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

    @api.depends("sequence", "is_down_payment", "withdrawal_id.installment_ids")
    def _compute_label(self):
        """'Entrega' para la entrega inicial; 'n/N' para las cuotas."""
        for installment in self:
            if installment.is_down_payment:
                installment.label = _("Entrega")
                continue
            total = len(installment.withdrawal_id.installment_ids.filtered(lambda i: not i.is_down_payment))
            installment.label = "%s/%s" % (installment.sequence, total)

    @api.depends("allocation_ids.amount", "allocation_ids.payment_id.state")
    def _compute_amount_allocated(self):
        """Suma de las imputaciones de pagos publicados sobre esta cuota."""
        for installment in self:
            installment.amount_allocated = sum(
                installment.allocation_ids
                .filtered(lambda a: a.payment_id.state == "posted")
                .mapped("amount")
            )

    @api.depends("amount", "amount_allocated", "late_fee")
    def _compute_amount_residual(self):
        """Residual de la cuota: monto más mora menos lo imputado, nunca negativo."""
        for installment in self:
            residual = installment.amount + installment.late_fee - installment.amount_allocated
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

        `cca_skip_total_check` existe para el reajuste de montos tras una corrección de
        precios: ahí las cuotas se escriben de a una y la suma queda descalzada a mitad
        de camino. Quien usa ese contexto invoca este constraint al terminar, así que el
        invariante se sigue verificando.
        """
        if self.env.context.get("cca_skip_total_check"):
            return
        for withdrawal in self.mapped("withdrawal_id").filtered("is_confirmed"):
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
        self.search([
            ("amount_residual", ">", 0),
            ("withdrawal_id.state", "not in", ("draft", "cancel")),
        ])._cca_update_late_fees()
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

    def write(self, vals):
        """En retiros confirmados, desde la pantalla solo se puede mover el vencimiento.

        `state` queda permitido porque el cron de vencidas lo recalcula y escribe.
        """
        if set(vals) - {"date_due", "late_fee", "state"} and not self.env.context.get("cca_skip_total_check") and any(
            installment.withdrawal_id.is_confirmed for installment in self
        ):
            raise UserError(_(
                "En un retiro confirmado solo se pueden cambiar los vencimientos de las cuotas."
            ))
        return super().write(vals)

    @api.model
    def _cca_to_collect_domain(self, days=7):
        """Cuotas para cobrar: impagas, de retiros vivos, vencidas o que vencen en `days` días."""
        limit = fields.Date.context_today(self) + relativedelta(days=days)
        return [
            ("amount_residual", ">", 0),
            ("withdrawal_id.state", "not in", ("draft", "cancel")),
            ("date_due", "<=", limit),
        ]

    def action_register_payment(self):
        """Botón Cobrar: abre el pago del cliente sugiriendo el saldo de esta cuota."""
        self.ensure_one()
        return self.env["cca.payment"]._cca_new_payment_action(self.partner_id, self.amount_residual)

    def _cca_update_late_fees(self):
        """Recalcula la mora de las cuotas impagas: días de atraso pasada la gracia × monto diario.

        Una cuota ya pagada no se toca: su mora queda congelada en lo que se cobró.
        `cca_today` en el contexto permite simular otra fecha (tests).
        """
        today = self.env.context.get("cca_today") or fields.Date.context_today(self)
        for installment in self:
            withdrawal = installment.withdrawal_id
            if not withdrawal.late_fee_enabled or not withdrawal.is_confirmed:
                continue
            if installment.withdrawal_id.is_cancelled or installment.is_down_payment:
                continue
            if installment.currency_id.is_zero(installment.amount_residual):
                continue
            days = (today - installment.date_due).days - (withdrawal.late_fee_grace_days or 0)
            fee = max(days, 0) * (withdrawal.late_fee_daily_amount or 0.0)
            if installment.currency_id.compare_amounts(fee, installment.late_fee) != 0:
                installment.sudo().write({"late_fee": fee})
        return True
