# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CawAllocateWizard(models.TransientModel):
    _name = "caw.allocate.wizard"
    _description = "Imputación manual de un pago a cuotas"

    payment_id = fields.Many2one(
        comodel_name="caw.payment",
        string="Pago",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="payment_id.currency_id", readonly=True)
    amount_available = fields.Monetary(
        string="Disponible",
        compute="_compute_amount_available",
        currency_field="currency_id",
    )
    amount_to_allocate = fields.Monetary(
        string="A imputar",
        compute="_compute_amount_to_allocate",
        currency_field="currency_id",
    )
    line_ids = fields.One2many(
        comodel_name="caw.allocate.wizard.line",
        inverse_name="wizard_id",
        string="Cuotas",
    )

    @api.model
    def default_get(self, fields_list):
        """Precarga las cuotas abiertas del partner en orden FIFO."""
        values = super().default_get(fields_list)
        payment_id = values.get("payment_id") or self.env.context.get("active_id")
        payment = self.env["caw.payment"].browse(payment_id)
        if payment:
            values["payment_id"] = payment.id
            values["line_ids"] = [
                (0, 0, {"installment_id": installment.id, "amount": 0.0})
                for installment in payment._caw_open_installments()
            ]
        return values

    @api.depends("payment_id.amount", "payment_id.amount_allocated")
    def _compute_amount_available(self):
        """Monto del pago todavía no imputado."""
        for wizard in self:
            payment = wizard.payment_id
            wizard.amount_available = payment.amount - payment.amount_allocated

    @api.depends("line_ids.amount")
    def _compute_amount_to_allocate(self):
        """Suma de los montos cargados en las líneas del wizard."""
        for wizard in self:
            wizard.amount_to_allocate = sum(wizard.line_ids.mapped("amount"))

    def action_allocate(self):
        """Crea las imputaciones elegidas, validando residuales y disponible."""
        self.ensure_one()
        currency = self.currency_id
        lines = self.line_ids.filtered(lambda l: currency.compare_amounts(l.amount, 0.0) > 0)
        if not lines:
            raise UserError(_("No cargaste ningún monto a imputar."))
        if currency.compare_amounts(sum(lines.mapped("amount")), self.amount_available) > 0:
            raise UserError(_(
                "Estás imputando %(total)s pero el pago solo tiene %(available)s disponible.",
                total=sum(lines.mapped("amount")),
                available=self.amount_available,
            ))
        for line in lines:
            if currency.compare_amounts(line.amount, line.installment_id.amount_residual) > 0:
                raise UserError(_(
                    "No se puede imputar %(amount)s a la cuota %(seq)s: su residual es %(residual)s.",
                    amount=line.amount,
                    seq=line.installment_id.sequence,
                    residual=line.installment_id.amount_residual,
                ))
        self.env["caw.allocation"].create([
            {
                "payment_id": self.payment_id.id,
                "installment_id": line.installment_id.id,
                "amount": line.amount,
            }
            for line in lines
        ])
        self.payment_id.message_post(body=_(
            "Imputación manual de %(total)s realizada por %(user)s.",
            total=sum(lines.mapped("amount")),
            user=self.env.user.display_name,
        ))
        return {"type": "ir.actions.act_window_close"}


class CawAllocateWizardLine(models.TransientModel):
    _name = "caw.allocate.wizard.line"
    _description = "Línea de imputación manual"
    _order = "wizard_id, id"

    wizard_id = fields.Many2one(
        comodel_name="caw.allocate.wizard",
        required=True,
        ondelete="cascade",
    )
    installment_id = fields.Many2one(
        comodel_name="caw.installment",
        string="Cuota",
        required=True,
        ondelete="cascade",
    )
    withdrawal_id = fields.Many2one(related="installment_id.withdrawal_id", readonly=True)
    date_due = fields.Date(related="installment_id.date_due", readonly=True)
    currency_id = fields.Many2one(related="wizard_id.currency_id", readonly=True)
    amount_residual = fields.Monetary(
        related="installment_id.amount_residual",
        string="Residual",
        readonly=True,
        currency_field="currency_id",
    )
    amount = fields.Monetary(
        string="A imputar",
        default=0.0,
        currency_field="currency_id",
    )
