# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CawPayment(models.Model):
    _name = "caw.payment"
    _description = "Pago de cuenta corriente"
    _inherit = ["mail.thread"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default="/")
    account_id = fields.Many2one(
        comodel_name="caw.account",
        string="Cuenta corriente",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        related="account_id.partner_id",
        store=True,
        index=True,
        string="Contacto",
    )
    company_id = fields.Many2one(
        related="account_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        index=True,
        tracking=True,
    )
    amount = fields.Monetary(
        string="Monto",
        required=True,
        currency_field="currency_id",
        tracking=True,
    )
    payment_method = fields.Selection(
        selection=[
            ("cash", "Efectivo"),
            ("transfer", "Transferencia"),
            ("check", "Cheque"),
            ("card", "Tarjeta"),
            ("other", "Otro"),
        ],
        string="Medio de pago",
        default="cash",
        required=True,
    )
    ref = fields.Char(string="Referencia")
    state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("posted", "Publicado"),
            ("cancel", "Anulado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )
    allocation_ids = fields.One2many(
        comodel_name="caw.allocation",
        inverse_name="payment_id",
        string="Imputaciones",
    )
    amount_allocated = fields.Monetary(
        string="Imputado",
        compute="_compute_allocated",
        store=True,
        currency_field="currency_id",
    )
    amount_unallocated = fields.Monetary(
        string="Saldo a favor",
        compute="_compute_allocated",
        store=True,
        currency_field="currency_id",
    )

    @api.depends("amount", "allocation_ids.amount", "state")
    def _compute_allocated(self):
        """Monto imputado y remanente disponible como saldo a favor."""
        for payment in self:
            allocated = sum(payment.allocation_ids.mapped("amount"))
            payment.amount_allocated = allocated
            payment.amount_unallocated = max(payment.amount - allocated, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna el número de secuencia del pago."""
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("caw.payment") or "/"
        return super().create(vals_list)

    def _caw_open_installments(self):
        """Cuotas abiertas del partner, ordenadas FIFO: vencimiento, luego retiro."""
        self.ensure_one()
        return self.env["caw.installment"].search(
            [
                ("partner_id", "=", self.partner_id.id),
                ("company_id", "=", self.company_id.id),
                ("amount_residual", ">", 0),
                ("withdrawal_id.state", "not in", ("draft", "cancel")),
            ],
            order="date_due asc, withdrawal_id asc, sequence asc",
        )

    def _caw_allocate_fifo(self):
        """Imputa el remanente del pago a las cuotas abiertas más antiguas."""
        allocation_model = self.env["caw.allocation"].sudo()
        for payment in self:
            remaining = payment.amount - payment.amount_allocated
            currency = payment.currency_id
            for installment in payment._caw_open_installments():
                if currency.compare_amounts(remaining, 0.0) <= 0:
                    break
                amount = min(remaining, installment.amount_residual)
                if currency.compare_amounts(amount, 0.0) <= 0:
                    continue
                allocation_model.create({
                    "payment_id": payment.id,
                    "installment_id": installment.id,
                    "amount": currency.round(amount),
                })
                remaining -= amount
            if currency.compare_amounts(remaining, 0.0) > 0:
                _logger.info(
                    "Pago %s: quedan %s sin imputar como saldo a favor de %s",
                    payment.name, remaining, payment.partner_id.display_name,
                )
        return True

    def action_post(self):
        """Publica el pago e imputa automáticamente por FIFO."""
        for payment in self:
            if payment.state != "draft":
                raise UserError(_("El pago %s ya fue publicado o anulado.", payment.name))
            if payment.currency_id.compare_amounts(payment.amount, 0.0) <= 0:
                raise UserError(_("El monto del pago %s debe ser mayor a cero.", payment.name))
            payment.state = "posted"
            payment._caw_allocate_fifo()
            payment.message_post(body=_("Pago publicado por %s.", self.env.user.display_name))
        return True

    def action_cancel(self):
        """Anula el pago revirtiendo todas sus imputaciones."""
        for payment in self:
            if payment.state == "cancel":
                raise UserError(_("El pago %s ya está anulado.", payment.name))
            payment.allocation_ids.unlink()
            payment.state = "cancel"
            payment.message_post(body=_("Pago anulado por %s.", self.env.user.display_name))
        return True

    def action_open_allocate_wizard(self):
        """Abre el wizard de imputación manual (solo Manager)."""
        self.ensure_one()
        if self.state != "posted":
            raise UserError(_("Solo se puede imputar manualmente un pago publicado."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Imputar el pago %s", self.name),
            "res_model": "caw.allocate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_payment_id": self.id, "active_id": self.id},
        }
