# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class CcaPayment(models.Model):
    _name = "cca.payment"
    _description = "Pago de cliente"
    _inherit = ["mail.thread"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default="/")
    account_id = fields.Many2one(
        comodel_name="cca.account",
        string="Cuenta corriente",
        required=True,
        ondelete="restrict",
        index=True,
    )
    partner_id = fields.Many2one(related="account_id.partner_id", store=True, index=True, string="Cliente")
    company_id = fields.Many2one(related="account_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today, index=True)
    amount = fields.Monetary(string="Monto", required=True, currency_field="currency_id")
    payment_method = fields.Selection(
        selection=[
            ("cash", "Efectivo"),
            ("transfer", "Transferencia"),
            ("card", "Tarjeta"),
            ("other", "Otro"),
        ],
        string="Medio de pago",
        default="cash",
        required=True,
    )
    ref = fields.Char(string="Referencia")
    state = fields.Selection(
        selection=[("posted", "Registrado"), ("cancel", "Anulado")],
        string="Estado",
        default="posted",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )
    allocation_ids = fields.One2many("cca.allocation", "payment_id", string="Imputaciones")
    amount_allocated = fields.Monetary(
        string="Imputado", compute="_compute_allocated", store=True, currency_field="currency_id"
    )
    amount_unallocated = fields.Monetary(
        string="Saldo a favor", compute="_compute_allocated", store=True, currency_field="currency_id"
    )

    @api.depends("amount", "allocation_ids.amount", "state")
    def _compute_allocated(self):
        """Imputado y remanente. Un pago anulado no deja saldo a favor."""
        for payment in self:
            allocated = sum(payment.allocation_ids.mapped("amount"))
            payment.amount_allocated = allocated
            payment.amount_unallocated = (
                max(payment.amount - allocated, 0.0) if payment.state == "posted" else 0.0
            )

    @api.constrains("amount")
    def _check_amount(self):
        """El monto debe ser mayor a cero."""
        for payment in self:
            if payment.currency_id.compare_amounts(payment.amount, 0.0) <= 0:
                raise ValidationError(_("El monto del pago debe ser mayor a cero."))

    @api.model_create_multi
    def create(self, vals_list):
        """Numera el pago y lo imputa por FIFO en el acto."""
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("cca.payment") or "/"
        payments = super().create(vals_list)
        payments._cca_allocate_fifo()
        return payments

    def _cca_open_installments(self):
        """Cuotas abiertas de la cuenta en orden FIFO: vencimiento, retiro, número."""
        self.ensure_one()
        return self.env["cca.installment"].search(
            [
                ("account_id", "=", self.account_id.id),
                ("amount_residual", ">", 0),
                ("withdrawal_id.state", "not in", ("draft", "cancel")),
            ],
            order="date_due asc, withdrawal_id asc, sequence asc",
        )

    def _cca_allocate_fifo(self):
        """Imputa el remanente de cada pago vigente a las cuotas abiertas más antiguas."""
        allocation_model = self.env["cca.allocation"].sudo()
        for payment in self.filtered(lambda p: p.state == "posted"):
            currency = payment.currency_id
            remaining = payment.amount - payment.amount_allocated
            for installment in payment._cca_open_installments():
                if currency.compare_amounts(remaining, 0.0) <= 0:
                    break
                amount = currency.round(min(remaining, installment.amount_residual))
                if currency.compare_amounts(amount, 0.0) <= 0:
                    continue
                allocation_model.create({
                    "payment_id": payment.id,
                    "installment_id": installment.id,
                    "amount": amount,
                })
                remaining -= amount
            if currency.compare_amounts(remaining, 0.0) > 0:
                _logger.info("Pago %s: %s queda como saldo a favor", payment.name, remaining)
        return True

    def action_cancel(self):
        """Anula el pago y deshace sus imputaciones."""
        for payment in self:
            if payment.state == "cancel":
                raise UserError(_("El pago %s ya está anulado.", payment.name))
            payment.allocation_ids.sudo().unlink()
            payment.state = "cancel"
            payment._message_log(body=_("Pago anulado por %s.", self.env.user.display_name))
        return True
