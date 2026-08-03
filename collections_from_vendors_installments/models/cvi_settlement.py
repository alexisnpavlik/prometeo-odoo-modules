# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("submitted", "Entregada"),
    ("approved", "Aprobada"),
    ("difference", "Con diferencia"),
]

FREQUENCY_SELECTION = [
    ("daily", "Diaria"),
    ("weekly", "Semanal"),
    ("monthly", "Mensual"),
]


class CviSettlement(models.Model):
    _name = "cvi.settlement"
    _description = "Rendición de caja de un cobrador"
    _inherit = ["mail.thread", "cvi.audit.mixin"]
    _order = "date_to desc, id desc"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        default=lambda self: _("Nueva"),
    )
    company_id = fields.Many2one(
        "res.company", string="Empresa", required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id", readonly=True,
    )
    collector_id = fields.Many2one(
        "res.users", string="Cobrador", required=True, index=True,
        default=lambda self: self.env.user,
    )
    date_to = fields.Date(
        string="Cierre del período", required=True,
        default=fields.Date.context_today, index=True,
    )
    frequency = fields.Selection(
        selection=FREQUENCY_SELECTION, string="Frecuencia", required=True,
        default=lambda self: self.env.company.cvi_settlement_frequency,
    )
    date_from = fields.Date(
        string="Inicio del período", compute="_compute_date_from", store=True,
    )
    state = fields.Selection(
        selection=STATE_SELECTION, string="Estado", default="draft",
        required=True, copy=False, tracking=True, index=True,
    )
    payment_ids = fields.One2many(
        "cvi.payment", "settlement_id", string="Cobros rendidos", readonly=True,
    )
    amount_expected = fields.Monetary(
        string="A rendir", compute="_compute_amounts", store=True,
        currency_field="currency_id",
    )
    payment_count = fields.Integer(
        string="Cobros", compute="_compute_amounts", store=True,
    )
    late_payment_count = fields.Integer(
        string="De períodos anteriores", compute="_compute_amounts", store=True,
        help="Cobros incluidos cuya fecha es anterior al inicio del período. No es un "
             "error: son cobros cargados tarde que no se habían rendido todavía.",
    )
    amount_delivered = fields.Monetary(
        string="Entregado", currency_field="currency_id", copy=False,
    )
    amount_difference = fields.Monetary(
        string="Diferencia", compute="_compute_difference", store=True,
        currency_field="currency_id",
        help="Entregado menos lo que había que rendir. Negativo es faltante.",
    )
    has_difference = fields.Boolean(
        string="Tiene diferencia", compute="_compute_difference", store=True,
    )
    note = fields.Text(string="Observación")
    approved_by_id = fields.Many2one(
        "res.users", string="Revisada por", readonly=True, copy=False,
    )
    approved_date = fields.Datetime(string="Revisada el", readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nueva")) == _("Nueva"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "cvi.settlement"
                ) or _("Nueva")
        return super().create(vals_list)

    @api.depends("date_to", "frequency")
    def _compute_date_from(self):
        """Inicio del período según la frecuencia configurada.

        Es una etiqueta, no un filtro: los cobros se juntan por settlement_id y por
        date <= date_to, sin límite inferior. Ver _cvi_pending_payments.
        """
        for settlement in self:
            if not settlement.date_to:
                settlement.date_from = False
                continue
            if settlement.frequency == "daily":
                settlement.date_from = settlement.date_to
            elif settlement.frequency == "weekly":
                settlement.date_from = settlement.date_to - relativedelta(days=6)
            else:
                settlement.date_from = settlement.date_to.replace(day=1)

    @api.depends("payment_ids.amount", "payment_ids.state", "date_from")
    def _compute_amounts(self):
        """Totaliza los cobros enganchados a la rendición."""
        for settlement in self:
            payments = settlement.payment_ids.filtered(
                lambda p: p.state == "posted"
            )
            settlement.amount_expected = sum(payments.mapped("amount"))
            settlement.payment_count = len(payments)
            settlement.late_payment_count = len(payments.filtered(
                lambda p: settlement.date_from and p.date < settlement.date_from
            ))

    @api.depends("amount_delivered", "amount_expected", "state")
    def _compute_difference(self):
        """Diferencia entre lo entregado y lo que había que rendir (HU-19)."""
        for settlement in self:
            rounding = settlement.currency_id.rounding or 0.01
            if settlement.state == "draft":
                settlement.amount_difference = 0.0
                settlement.has_difference = False
                continue
            difference = settlement.amount_delivered - settlement.amount_expected
            settlement.amount_difference = difference
            settlement.has_difference = not float_is_zero(
                difference, precision_rounding=rounding
            )

    def _cvi_pending_payments(self):
        """Cobros del cobrador que todavía no se rindieron (HU-18).

        Sin límite inferior de fecha a propósito: un cobro cargado tarde, con fecha de
        un período ya rendido, entra en la próxima rendición abierta en vez de quedar
        huérfano. settlement_id es la única fuente de verdad sobre qué ya se rindió.

        Las comisiones quedan afuera. Por RN-01 la primera cuota es del vendedor: nunca
        entra a la caja de la empresa, así que reclamársela sería pedirle plata propia.
        Importa desde que existe el perfil híbrido, porque un vendedor que además cobra
        registra sus comisiones con su mismo usuario.
        """
        self.ensure_one()
        return self.env["cvi.payment"].search([
            ("user_id", "=", self.collector_id.id),
            ("company_id", "=", self.company_id.id),
            ("state", "=", "posted"),
            ("settlement_id", "=", False),
            ("is_commission", "=", False),
            ("date", "<=", self.date_to),
        ])

    def action_collect(self):
        """Engancha a la rendición los cobros pendientes del cobrador (HU-18)."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_(
                "La rendición %s ya fue entregada: no se le pueden agregar cobros.",
                self.name,
            ))
        pending = self._cvi_pending_payments()
        if pending:
            pending.write({"settlement_id": self.id})
        return True

    def action_submit(self):
        """El cobrador entrega la caja y la deja a revisión (HU-19)."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_(
                "La rendición %(name)s ya está en estado %(state)s.",
                name=self.name, state=dict(STATE_SELECTION)[self.state],
            ))
        self.action_collect()
        if not self.payment_ids:
            raise UserError(_(
                "No hay cobros pendientes de rendir para %s.", self.collector_id.name
            ))
        self.state = "submitted"
        self._cvi_log(_(
            "Rendición entregada por %(user)s: %(count)s cobros, a rendir %(expected)s, "
            "entregado %(delivered)s.",
            user=self.env.user.name,
            count=self.payment_count,
            expected=self.amount_expected,
            delivered=self.amount_delivered,
        ))
        return True

    def action_approve(self):
        """El administrador aprueba una rendición que cuadra (HU-20)."""
        self.ensure_one()
        if self.state != "submitted":
            raise UserError(_(
                "Solo se aprueba una rendición entregada. %(name)s está en %(state)s.",
                name=self.name, state=dict(STATE_SELECTION)[self.state],
            ))
        if self.has_difference:
            raise UserError(_(
                "La rendición %(name)s tiene una diferencia de %(diff)s. Usá "
                "\"Aprobar con diferencia\" y dejá una observación.",
                name=self.name, diff=self.amount_difference,
            ))
        self._cvi_close("approved")
        return True

    def action_flag_difference(self):
        """Aprueba dejando la diferencia registrada y explicada (HU-20)."""
        self.ensure_one()
        if self.state != "submitted":
            raise UserError(_(
                "Solo se cierra una rendición entregada. %(name)s está en %(state)s.",
                name=self.name, state=dict(STATE_SELECTION)[self.state],
            ))
        if not self.note:
            raise UserError(_(
                "Cargá una observación explicando la diferencia de %s.",
                self.amount_difference,
            ))
        self._cvi_close("difference")
        return True

    def _cvi_close(self, state):
        """Cierra la rendición dejando quién la revisó y cuándo."""
        self.ensure_one()
        self.write({
            "state": state,
            "approved_by_id": self.env.user.id,
            "approved_date": fields.Datetime.now(),
        })
        self._cvi_log(_(
            "Rendición cerrada como %(state)s por %(user)s. Diferencia: %(diff)s.",
            state=dict(STATE_SELECTION)[state],
            user=self.env.user.name,
            diff=self.amount_difference,
        ))
        _logger.info(
            "Rendición %s cerrada como %s con diferencia %s",
            self.name, state, self.amount_difference,
        )
        return True

    def action_reset_draft(self):
        """Devuelve la rendición a borrador y libera sus cobros (HU-20)."""
        self.ensure_one()
        if self.state == "draft":
            raise UserError(_("La rendición %s ya está en borrador.", self.name))
        self.payment_ids.write({"settlement_id": False})
        self.write({
            "state": "draft",
            "approved_by_id": False,
            "approved_date": False,
        })
        self._cvi_log(_("Rendición reabierta por %s: sus cobros vuelven a estar pendientes.", self.env.user.name))
        return True

    def unlink(self):
        """Una rendición entregada no se borra: se reabre y después sí.

        Borrarla dejaría los cobros marcados como rendidos apuntando a nada.
        """
        locked = self.filtered(lambda s: s.state != "draft")
        if locked:
            raise UserError(_(
                "No se puede borrar la rendición %s: ya fue entregada. Reabrila primero.",
                locked[0].name,
            ))
        return super().unlink()
