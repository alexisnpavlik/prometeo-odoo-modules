# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class CviPaymentWizard(models.TransientModel):
    _name = "cvi.payment.wizard"
    _description = "Registrar el cobro de una cuota"

    card_id = fields.Many2one(
        "cvi.card", string="Tarjeta", required=True, readonly=True,
    )
    installment_id = fields.Many2one(
        "cvi.installment", string="Cuota", readonly=True,
    )
    customer_id = fields.Many2one(
        related="card_id.customer_id", string="Cliente", readonly=True,
    )
    currency_id = fields.Many2one(related="card_id.currency_id", readonly=True)
    date = fields.Date(
        string="Fecha del cobro", required=True, default=fields.Date.context_today,
    )
    amount = fields.Monetary(
        string="Monto que paga", required=True, currency_field="currency_id",
        help="Viene cargado con lo que falta de esta cuota. Cambialo por lo que el "
             "cliente entrega realmente.",
    )
    is_commission = fields.Boolean(string="Es la entrega del vendedor", readonly=True)
    note = fields.Char(string="Observación")

    # Los tres importes salen del mismo compute a propósito: ninguno se pasa nunca en el
    # create (son readonly y no tienen default), así que la protección de Odoo contra
    # pisar valores explícitos no se activa y no hay riesgo de que se saltee.
    amount_installment = fields.Monetary(
        string="Falta de esta cuota", compute="_compute_amounts",
        currency_field="currency_id",
    )
    amount_due_before = fields.Monetary(
        string="Impago de cuotas anteriores", compute="_compute_amounts",
        currency_field="currency_id",
        help="Lo que quedó sin pagar de las cuotas que vencen antes que ésta. Un cobro "
             "tapa siempre la deuda más vieja primero.",
    )
    amount_max = fields.Monetary(
        string="Debe en total", compute="_compute_amounts",
        currency_field="currency_id",
    )

    @api.depends("card_id", "installment_id", "is_commission")
    def _compute_amounts(self):
        """Lo que falta de esta cuota, lo atrasado de las anteriores y el total.

        Se mira solo el lote que corresponde: la comisión del vendedor y la cobranza
        del cobrador son plata de distinta gente y nunca se mezclan (RN-01).
        """
        for wizard in self:
            pending = wizard.card_id.installment_ids.filtered(
                lambda i: (
                    i.amount_residual > 0
                    and i.is_commission == wizard.is_commission
                )
            )
            current = wizard.installment_id
            wizard.amount_installment = current.amount_residual
            wizard.amount_max = sum(pending.mapped("amount_residual"))
            if current:
                wizard.amount_due_before = sum(
                    i.amount_residual for i in pending
                    if (i.date_due, i.sequence) < (current.date_due, current.sequence)
                )
            else:
                wizard.amount_due_before = 0.0

    def action_charge_everything_due(self):
        """Carga en el monto todo lo que el cliente adeuda hasta esta cuota inclusive.

        Es el caso que motivó el asistente: el cliente que el mes pasado pagó de menos
        y ahora se pone al día. De un toque, sin que el cobrador sume de memoria.
        """
        self.ensure_one()
        self.amount = self.amount_due_before + self.amount_installment
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
        }

    def action_confirm_payment(self):
        """Crea el cobro por el monto indicado y lo imputa (HU-15).

        La imputación es FIFO y la hace cvi.payment: lo que entra tapa primero la cuota
        más vieja impaga. Por eso un pago parcial no se pierde ni hay que arrastrarlo a
        mano: el mes siguiente el sobrante de la cuota vieja se cancela solo.
        """
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        if float_compare(self.amount, self.amount_max, precision_rounding=rounding) > 0:
            raise UserError(_(
                "El cliente no debe tanto. La tarjeta %(card)s adeuda %(due)s y "
                "estás cobrando %(amount)s.",
                card=self.card_id.name,
                due=self.amount_max,
                amount=self.amount,
            ))
        if self.is_commission:
            # La comisión la cobra el vendedor aunque el que registra sea otro (RN-01).
            payment = self.card_id.action_charge_first_installment(
                amount=self.amount, date=self.date,
            )
            if self.note:
                payment.note = self.note
            return {"type": "ir.actions.act_window_close"}
        payment = self.env["cvi.payment"].create({
            "card_id": self.card_id.id,
            "date": self.date,
            "amount": self.amount,
            "user_id": self.env.user.id,
            "note": self.note,
        })
        payment.action_post()
        return {"type": "ir.actions.act_window_close"}
