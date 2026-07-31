# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CviAllocation(models.Model):
    _name = "cvi.allocation"
    _description = "Imputación de un cobro sobre una cuota"
    _order = "installment_id, id"

    payment_id = fields.Many2one(
        "cvi.payment", string="Cobro", required=True, ondelete="cascade", index=True
    )
    installment_id = fields.Many2one(
        "cvi.installment", string="Cuota", required=True, ondelete="cascade", index=True
    )
    card_id = fields.Many2one(
        related="installment_id.card_id", store=True, index=True, string="Tarjeta"
    )
    currency_id = fields.Many2one(related="installment_id.currency_id", readonly=True)
    company_id = fields.Many2one(
        related="installment_id.company_id", store=True, index=True, string="Empresa"
    )
    amount = fields.Monetary(
        string="Monto imputado", required=True, currency_field="currency_id"
    )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto imputado debe ser mayor a cero.",
        ),
    ]
