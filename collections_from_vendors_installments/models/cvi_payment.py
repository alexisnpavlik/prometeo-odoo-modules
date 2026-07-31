# -*- coding: utf-8 -*-
from odoo import _, fields, models

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("posted", "Registrado"),
    ("cancel", "Anulado"),
]


class CviPayment(models.Model):
    _name = "cvi.payment"
    _description = "Cobro de cuotas de una tarjeta"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        default=lambda self: _("Nuevo"),
    )
    card_id = fields.Many2one(
        "cvi.card", string="Tarjeta", required=True, ondelete="restrict", index=True
    )
    partner_id = fields.Many2one(
        related="card_id.partner_id", store=True, index=True, string="Cliente"
    )
    company_id = fields.Many2one(related="card_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="card_id.currency_id", readonly=True)
    date = fields.Date(
        string="Fecha", required=True, default=fields.Date.context_today, index=True
    )
    amount = fields.Monetary(
        string="Monto cobrado", required=True, currency_field="currency_id"
    )
    user_id = fields.Many2one(
        "res.users", string="Cobrado por", required=True,
        default=lambda self: self.env.user, readonly=True, index=True,
    )
    is_commission = fields.Boolean(
        string="Comisión del vendedor", default=False,
        help="Marca el cobro de la primera cuota, que hace el vendedor (RN-01).",
    )
    state = fields.Selection(
        selection=STATE_SELECTION, string="Estado", default="draft",
        required=True, copy=False, tracking=True, index=True,
    )
    allocation_ids = fields.One2many(
        "cvi.allocation", "payment_id", string="Imputaciones"
    )
    note = fields.Char(string="Observación")

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto cobrado debe ser mayor a cero.",
        ),
    ]
