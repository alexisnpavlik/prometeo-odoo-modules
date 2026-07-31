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
    _description = "Cuota de una tarjeta de venta en cuotas"
    _order = "date_due, card_id, sequence, id"

    card_id = fields.Many2one(
        "cvi.card",
        string="Tarjeta",
        required=True,
        ondelete="cascade",
        index=True,
    )
    customer_id = fields.Many2one(
        related="card_id.customer_id", store=True, index=True, string="Cliente"
    )
    collector_id = fields.Many2one(
        related="card_id.collector_id", store=True, index=True, string="Cobrador"
    )
    street = fields.Char(
        related="customer_id.street", store=True, string="Dirección"
    )
    city = fields.Char(related="customer_id.city", store=True, string="Ciudad")
    phone = fields.Char(related="customer_id.phone", string="Teléfono")
    card_residual = fields.Monetary(
        related="card_id.amount_residual",
        string="Saldo de la tarjeta",
        currency_field="currency_id",
    )
    card_state = fields.Selection(
        related="card_id.state", store=True, string="Estado de la tarjeta"
    )
    map_url = fields.Char(string="Mapa", compute="_compute_map_url")
    map_is_gps = fields.Boolean(
        string="Ubicación GPS",
        compute="_compute_map_url",
        help="Verdadero si el mapa apunta a las coordenadas tomadas al vender. "
             "Falso si cae de vuelta a la dirección cargada en el contacto.",
    )
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
    # Distinto de collector_id, que es el cobrador ASIGNADO a la tarjeta hoy. Cuando una
    # cartera se transfiere, el asignado cambia pero quien cobró cada cuota no.
    collected_by_ids = fields.Many2many(
        "res.users",
        string="Cobrado por",
        compute="_compute_collected_by",
        help="Quién registró efectivamente el cobro de esta cuota. Puede diferir del "
             "cobrador asignado si la cartera se transfirió después.",
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

    @api.depends("allocation_ids.payment_id.state", "allocation_ids.payment_id.user_id")
    def _compute_collected_by(self):
        """Usuarios que registraron los cobros publicados imputados a esta cuota."""
        for installment in self:
            installment.collected_by_ids = (
                installment.allocation_ids
                .filtered(lambda a: a.payment_id.state == "posted")
                .mapped("payment_id.user_id")
            )

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

    def action_register_payment(self):
        """Abre el asistente de cobro con el monto de esta cuota ya cargado (HU-15).

        El monto viene sugerido, no impuesto: el cliente paga lo que puede y el
        asistente deja cambiarlo antes de registrar.
        """
        self.ensure_one()
        if self.state == "paid":
            raise UserError(_(
                "La cuota %(seq)s de %(card)s ya está pagada.",
                seq=self.sequence, card=self.card_id.name,
            ))
        if self.card_id.state in ("draft", "cancel"):
            raise UserError(_(
                "La tarjeta %s no está en cobranza: no se le pueden registrar cobros.",
                self.card_id.name,
            ))
        context = {
            "default_card_id": self.card_id.id,
            "default_installment_id": self.id,
            "default_amount": self.amount_residual,
            "default_is_commission": self.is_commission,
        }
        # La fecha de cobro de la entrega puede haberse anotado al cargar la venta.
        # Solo se pasa si tiene valor: un default False dejaría el campo vacío.
        if self.is_commission and self.card_id.date_first_payment:
            context["default_date"] = self.card_id.date_first_payment
        return {
            "type": "ir.actions.act_window",
            "name": _("Registrar cobro"),
            "res_model": "cvi.payment.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": context,
        }

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

    @api.depends(
        "card_id.has_geolocation",
        "card_id.map_url",
        "customer_id.street",
        "customer_id.city",
        "customer_id.zip",
    )
    def _compute_map_url(self):
        """Link al mapa para armar el recorrido (HU-07, HU-14).

        Prioriza las coordenadas GPS tomadas al vender sobre la dirección del contacto:
        la dirección nominal suele no coincidir con dónde está la casa. La dirección
        queda como respaldo para las ventas cargadas antes de que existiera el GPS; el
        campo map_is_gps dice cuál de las dos se está usando, para que el cobrador no
        confunda un respaldo con una ubicación tomada en el lugar.
        """
        for installment in self:
            card = installment.card_id
            if card.has_geolocation:
                installment.map_url = card.map_url
                installment.map_is_gps = True
                continue
            installment.map_is_gps = False
            customer = installment.customer_id
            parts = [customer.street, customer.city, customer.zip]
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
                "El cliente %s no tiene dirección cargada.", self.customer_id.display_name
            ))
        return {
            "type": "ir.actions.act_url",
            "url": self.map_url,
            "target": "new",
        }
