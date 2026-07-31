# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("posted", "Registrado"),
    ("cancel", "Anulado"),
]


class CviPayment(models.Model):
    _name = "cvi.payment"
    _description = "Cobro de cuotas de una tarjeta"
    _inherit = ["mail.thread", "cvi.audit.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        default=lambda self: _("Nuevo"),
    )
    card_id = fields.Many2one(
        "cvi.card", string="Tarjeta", required=True, ondelete="restrict", index=True
    )
    customer_id = fields.Many2one(
        related="card_id.customer_id", store=True, index=True, string="Cliente"
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
    settlement_id = fields.Many2one(
        "cvi.settlement", string="Rendición", readonly=True, copy=False,
        index=True, ondelete="restrict",
        help="Rendición de caja en la que se entregó este cobro (HU-18).",
    )
    note = fields.Char(string="Observación")

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "El monto cobrado debe ser mayor a cero.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna la referencia desde la secuencia al crear."""
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cvi.payment") or _("Nuevo")
        return super().create(vals_list)

    def unlink(self):
        """Un cobro publicado o anulado nunca se borra: queda como registro (RN-06)."""
        if any(payment.state != "draft" for payment in self):
            raise UserError(_(
                "Un cobro registrado no se puede eliminar. Anulalo con el botón Anular "
                "para que quede constancia."
            ))
        return super().unlink()

    def _cvi_target_installments(self):
        """Cuotas candidatas a recibir esta imputación, en orden FIFO por vencimiento.

        Un cobro de comisión solo toca la cuota del vendedor; un cobro normal solo toca
        las cuotas de cobranza. Así el cobrador nunca ve la comisión como pendiente (HU-09).
        """
        self.ensure_one()
        return self.card_id.installment_ids.filtered(
            lambda i: i.amount_residual > 0 and i.is_commission == self.is_commission
        ).sorted(lambda i: (i.date_due, i.sequence))

    def _cvi_allocate(self):
        """Reparte el monto del cobro sobre las cuotas candidatas. Devuelve el sobrante."""
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        remaining = self.amount
        vals_list = []
        for installment in self._cvi_target_installments():
            if float_is_zero(remaining, precision_rounding=rounding):
                break
            applied = min(remaining, installment.amount_residual)
            vals_list.append({
                "payment_id": self.id,
                "installment_id": installment.id,
                "amount": applied,
            })
            remaining -= applied
        if vals_list:
            self.env["cvi.allocation"].create(vals_list)
        return remaining

    def action_post(self):
        """Publica el cobro e imputa su monto sobre las cuotas impagas (HU-15)."""
        for payment in self:
            if payment.state != "draft":
                raise UserError(_(
                    "El cobro %s ya fue registrado: no se puede volver a registrar.",
                    payment.name,
                ))
            payment.state = "posted"
            leftover = payment._cvi_allocate()
            rounding = payment.currency_id.rounding or 0.01
            if float_compare(leftover, 0.0, precision_rounding=rounding) > 0:
                raise UserError(_(
                    "El cobro de %(amount)s supera lo que adeuda la tarjeta %(card)s: "
                    "sobran %(left)s sin imputar.",
                    amount=payment.amount,
                    card=payment.card_id.name,
                    left=leftover,
                ))
            payment.card_id._cvi_log(_(
                "Cobro %(name)s por %(amount)s registrado por %(user)s.",
                name=payment.name, amount=payment.amount, user=payment.user_id.name,
            ))
            payment.card_id._cvi_check_settlement()
        return True

    def action_cancel(self):
        """Anula el cobro y libera las cuotas que había imputado (RN-06)."""
        for payment in self:
            if payment.state != "posted":
                raise UserError(_(
                    "Solo se puede anular un cobro registrado (el cobro %s está en estado %s).",
                    payment.name, payment.state,
                ))
            # Un cobro ya rendido está respaldado por plata entregada en caja: anularlo
            # dejaría la rendición cerrada cuadrando contra un cobro que ya no existe.
            if payment.settlement_id:
                raise UserError(_(
                    "El cobro %(name)s ya se rindió en %(settlement)s. Reabrí la "
                    "rendición antes de anularlo.",
                    name=payment.name, settlement=payment.settlement_id.name,
                ))
            payment.allocation_ids.unlink()
            payment.state = "cancel"
            payment.card_id._cvi_log(_(
                "Cobro %(name)s por %(amount)s ANULADO por %(user)s.",
                name=payment.name, amount=payment.amount, user=self.env.user.name,
            ))
            payment.card_id._cvi_check_settlement()
        return True
