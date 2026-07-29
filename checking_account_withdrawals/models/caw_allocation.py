# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CawAllocation(models.Model):
    _name = "caw.allocation"
    _description = "Imputación de pago a cuota de cuenta corriente"
    _order = "payment_id, installment_id, id"

    payment_id = fields.Many2one(
        comodel_name="caw.payment",
        string="Pago",
        required=True,
        ondelete="cascade",
        index=True,
    )
    installment_id = fields.Many2one(
        comodel_name="caw.installment",
        string="Cuota",
        required=True,
        ondelete="cascade",
        index=True,
    )
    withdrawal_id = fields.Many2one(
        related="installment_id.withdrawal_id",
        store=True,
        index=True,
        string="Retiro",
    )
    partner_id = fields.Many2one(related="installment_id.partner_id", store=True, index=True)
    company_id = fields.Many2one(related="payment_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="payment_id.currency_id", readonly=True)
    date = fields.Date(related="payment_id.date", store=True, index=True)
    amount = fields.Monetary(
        string="Monto imputado",
        required=True,
        currency_field="currency_id",
    )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto imputado debe ser mayor a cero.",
        ),
    ]

    @api.constrains("amount", "installment_id", "payment_id")
    def _check_amounts(self):
        """No se puede imputar más que el residual de la cuota ni más que el pago."""
        for allocation in self:
            installment = allocation.installment_id
            currency = allocation.currency_id
            others = sum(
                installment.allocation_ids.filtered(lambda a: a.id != allocation.id).mapped("amount")
            )
            if currency.compare_amounts(others + allocation.amount, installment.amount) > 0:
                raise ValidationError(_(
                    "No se puede imputar %(amount)s a la cuota %(seq)s: supera su residual.",
                    amount=allocation.amount,
                    seq=installment.sequence,
                ))
            payment = allocation.payment_id
            total_allocated = sum(payment.allocation_ids.mapped("amount"))
            if currency.compare_amounts(total_allocated, payment.amount) > 0:
                raise ValidationError(_(
                    "Las imputaciones del pago %(name)s (%(alloc)s) superan su monto (%(amount)s).",
                    name=payment.name,
                    alloc=total_allocated,
                    amount=payment.amount,
                ))
