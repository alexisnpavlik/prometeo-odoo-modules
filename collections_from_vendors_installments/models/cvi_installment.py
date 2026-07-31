# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero
from werkzeug.urls import url_encode

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("pending", "Pendiente"),
    ("partial", "Parcial"),
    ("paid", "Pagada"),
    ("overdue", "Vencida"),
]


class CviInstallment(models.Model):
    _name = "cvi.installment"
    _inherit = ["cvi.audit.mixin"]
    _description = "Cuota de una tarjeta de venta en cuotas"
    _order = "date_due, card_id, sequence, id"

    card_id = fields.Many2one(
        "cvi.card",
        string="Tarjeta",
        required=True,
        ondelete="cascade",
        index=True,
    )
    partner_id = fields.Many2one(
        related="card_id.partner_id", store=True, index=True, string="Cliente"
    )
    collector_id = fields.Many2one(
        related="card_id.collector_id", store=True, index=True, string="Cobrador"
    )
    street = fields.Char(
        related="partner_id.street", store=True, string="Dirección"
    )
    city = fields.Char(related="partner_id.city", store=True, string="Ciudad")
    phone = fields.Char(related="partner_id.phone", string="Teléfono")
    card_residual = fields.Monetary(
        related="card_id.amount_residual",
        string="Saldo de la tarjeta",
        currency_field="currency_id",
    )
    card_state = fields.Selection(
        related="card_id.state", store=True, string="Estado de la tarjeta"
    )
    map_url = fields.Char(string="Mapa", compute="_compute_map_url")
    company_id = fields.Many2one(related="card_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="card_id.currency_id", readonly=True)
    sequence = fields.Integer(string="Nº de cuota", default=1, required=True)
    date_due = fields.Date(string="Vencimiento", required=True, index=True)
    amount = fields.Monetary(
        string="Monto", required=True, currency_field="currency_id"
    )
    is_commission = fields.Boolean(
        string="Comisión del vendedor",
        default=False,
        help="La primera cuota la cobra el vendedor y constituye su comisión (RN-01). "
             "No forma parte de la cobranza del cobrador.",
    )
    allocation_ids = fields.One2many(
        "cvi.allocation", "installment_id", string="Imputaciones"
    )
    amount_paid = fields.Monetary(
        string="Cobrado",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_residual = fields.Monetary(
        string="Residual",
        compute="_compute_amounts",
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

    @api.depends("amount", "allocation_ids.amount", "allocation_ids.payment_id.state")
    def _compute_amounts(self):
        """Cobrado = imputaciones de cobros publicados. Residual nunca es negativo."""
        for installment in self:
            paid = sum(
                installment.allocation_ids
                .filtered(lambda a: a.payment_id.state == "posted")
                .mapped("amount")
            )
            installment.amount_paid = paid
            installment.amount_residual = max(installment.amount - paid, 0.0)

    @api.depends("amount", "amount_paid", "amount_residual", "date_due", "company_id.cvi_overdue_days")
    def _compute_state(self):
        """Estado de la cuota. Solo es pagada cuando el residual llega a cero."""
        today = fields.Date.context_today(self)
        for installment in self:
            rounding = installment.currency_id.rounding or 0.01
            tolerance = installment.company_id.cvi_overdue_days or 0
            if float_is_zero(installment.amount_residual, precision_rounding=rounding):
                installment.state = "paid"
            elif installment.date_due and (today - installment.date_due).days > tolerance:
                installment.state = "overdue"
            elif installment.amount_paid > 0:
                installment.state = "partial"
            else:
                installment.state = "pending"

    def action_postpone(self, new_date):
        """Corre el vencimiento de una cuota impaga a pedido del cliente.

        El vendedor fija el día de cobro al vender, pero el cliente puede pedir mover una
        fecha puntual. Solo mueve esta cuota; el resto del calendario queda igual.
        """
        self.ensure_one()
        if self.state == "paid":
            raise UserError(_("La cuota %s ya está pagada: no se puede reprogramar.", self.sequence))
        new_date = fields.Date.to_date(new_date)
        if new_date < self.card_id.date_sale:
            raise UserError(_(
                "No se puede reprogramar la cuota a %(new)s: es anterior a la fecha de venta (%(sale)s).",
                new=new_date,
                sale=self.card_id.date_sale,
            ))
        old_date = self.date_due
        self.date_due = new_date
        self.card_id._cvi_log(_(
            "Cuota %(seq)s reprogramada de %(old)s a %(new)s.",
            seq=self.sequence, old=old_date, new=new_date,
        ))
        return True

    @api.model
    def _cron_update_overdue(self):
        """Cron diario: recalcula el estado de las cuotas impagas ya vencidas (HU-23 parcial).

        El estado es computado y almacenado pero depende de la fecha de hoy, que no es un
        campo. Este cron fuerza el recálculo invalidando la caché de las candidatas.
        """
        today = fields.Date.context_today(self)
        candidates = self.search([
            ("date_due", "<", today),
            ("state", "in", ("pending", "partial")),
            ("card_id.state", "not in", ("draft", "cancel")),
        ])
        candidates.invalidate_recordset(["state"])
        candidates._compute_state()
        _logger.info("Cron de cuotas vencidas: %s cuotas revisadas", len(candidates))
        return True

    @api.depends("partner_id.street", "partner_id.city", "partner_id.zip")
    def _compute_map_url(self):
        """Link a Google Maps con la dirección del cliente, para armar el recorrido (HU-14)."""
        for installment in self:
            partner = installment.partner_id
            parts = [partner.street, partner.city, partner.zip]
            address = ", ".join(part for part in parts if part)
            if address:
                query = url_encode({"api": "1", "query": address})
                installment.map_url = "https://www.google.com/maps/search/?%s" % query
            else:
                installment.map_url = False

    def action_open_map(self):
        """Abre la ubicación del cliente en el mapa, en una pestaña nueva (HU-14)."""
        self.ensure_one()
        if not self.map_url:
            raise UserError(_(
                "El cliente %s no tiene dirección cargada.", self.partner_id.display_name
            ))
        return {
            "type": "ir.actions.act_url",
            "url": self.map_url,
            "target": "new",
        }
