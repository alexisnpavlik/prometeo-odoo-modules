# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

RESULT_SELECTION = [
    ("compliant", "Conforme"),
    ("issues", "Con observaciones"),
]

VISIT_STATE_SELECTION = [
    ("draft", "En curso"),
    ("done", "Cerrada"),
]


class CviSupervisionAssignment(models.Model):
    _name = "cvi.supervision.assignment"
    _description = "Asignación de un cobrador a un supervisor"
    _order = "date_start desc, id desc"

    supervisor_id = fields.Many2one(
        "res.users", string="Supervisor", required=True, index=True, ondelete="cascade",
    )
    collector_id = fields.Many2one(
        "res.users", string="Cobrador", required=True, index=True, ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company", string="Empresa", required=True, index=True,
        default=lambda self: self.env.company,
    )
    date_start = fields.Date(
        string="Desde", required=True, default=fields.Date.context_today,
    )
    date_end = fields.Date(
        string="Hasta",
        help="Vacío significa vigente sin fecha de corte.",
    )
    active = fields.Boolean(string="Activa", default=True)

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for assignment in self:
            if assignment.date_end and assignment.date_end < assignment.date_start:
                raise ValidationError(_(
                    "La asignación de %s termina antes de empezar.",
                    assignment.collector_id.name,
                ))

    @api.constrains("supervisor_id", "collector_id")
    def _check_not_self(self):
        for assignment in self:
            if assignment.supervisor_id == assignment.collector_id:
                raise ValidationError(_(
                    "Un cobrador no puede supervisarse a sí mismo."
                ))

    @api.model
    def _cvi_current_domain(self):
        """Asignaciones vigentes hoy: empezadas y sin fecha de corte pasada (HU-21)."""
        today = fields.Date.context_today(self)
        return [
            ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ]


class CviSupervisionVisit(models.Model):
    _name = "cvi.supervision.visit"
    _description = "Visita de supervisión sobre la cartera de un cobrador"
    _inherit = ["mail.thread", "mail.activity.mixin", "cvi.audit.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        default=lambda self: _("Nueva"),
    )
    supervisor_id = fields.Many2one(
        "res.users", string="Supervisor", required=True, index=True,
        default=lambda self: self.env.user,
    )
    collector_id = fields.Many2one(
        "res.users", string="Cobrador auditado", required=True, index=True,
    )
    company_id = fields.Many2one(
        "res.company", string="Empresa", required=True, index=True,
        default=lambda self: self.env.company,
    )
    date = fields.Date(
        string="Fecha de la visita", required=True, default=fields.Date.context_today,
    )
    date_from = fields.Date(string="Período auditado desde", required=True)
    date_to = fields.Date(string="Período auditado hasta", required=True)
    line_ids = fields.One2many(
        "cvi.supervision.line", "visit_id", string="Tarjetas revisadas",
    )
    result = fields.Selection(
        selection=RESULT_SELECTION, string="Resultado",
        compute="_compute_result", store=True, readonly=False,
        help="Se propone según las tarjetas con observación, pero el supervisor "
             "puede corregirlo.",
    )
    state = fields.Selection(
        selection=VISIT_STATE_SELECTION, string="Estado", default="draft",
        required=True, copy=False, tracking=True, index=True,
    )
    note = fields.Text(string="Observaciones generales")
    card_count = fields.Integer(
        string="Tarjetas revisadas", compute="_compute_result", store=True,
    )
    issue_count = fields.Integer(
        string="Con observación", compute="_compute_result", store=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nueva")) == _("Nueva"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "cvi.supervision.visit"
                ) or _("Nueva")
        return super().create(vals_list)

    @api.constrains("date_from", "date_to")
    def _check_period(self):
        for visit in self:
            if visit.date_to < visit.date_from:
                raise ValidationError(_(
                    "El período auditado de %s termina antes de empezar.", visit.name
                ))

    @api.depends("line_ids.has_issue")
    def _compute_result(self):
        """Propone el resultado a partir de las tarjetas revisadas (HU-22)."""
        for visit in self:
            visit.card_count = len(visit.line_ids)
            issues = visit.line_ids.filtered("has_issue")
            visit.issue_count = len(issues)
            visit.result = "issues" if issues else "compliant"

    def action_load_cards(self):
        """Trae las tarjetas de la cartera del cobrador en el período auditado.

        Evita que el supervisor las cargue a mano una por una, que es donde se pierde
        la trazabilidad de qué se revisó y qué no.
        """
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("La visita %s ya está cerrada.", self.name))
        cards = self.env["cvi.card"].search([
            ("collector_id", "=", self.collector_id.id),
            ("company_id", "=", self.company_id.id),
            ("state", "in", ("active", "routed")),
        ])
        existing = self.line_ids.mapped("card_id")
        missing = cards - existing
        if missing:
            self.line_ids = [(0, 0, {"card_id": card.id}) for card in missing]
        return True

    def action_close(self):
        """Cierra la visita y deja el resultado asentado (HU-22)."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("La visita %s ya está cerrada.", self.name))
        if not self.line_ids:
            raise UserError(_(
                "Marcá al menos una tarjeta revisada antes de cerrar la visita."
            ))
        self.state = "done"
        self._cvi_log(_(
            "Visita cerrada por %(user)s: %(count)s tarjetas revisadas, "
            "%(issues)s con observación. Resultado: %(result)s.",
            user=self.env.user.name,
            count=self.card_count,
            issues=self.issue_count,
            result=dict(RESULT_SELECTION)[self.result],
        ))
        _logger.info(
            "Visita de supervisión %s cerrada sobre %s: %s observaciones",
            self.name, self.collector_id.name, self.issue_count,
        )
        return True

    def action_reopen(self):
        """Reabre una visita cerrada para corregirla."""
        self.ensure_one()
        if self.state != "done":
            raise UserError(_("La visita %s no está cerrada.", self.name))
        self.state = "draft"
        self._cvi_log(_("Visita reabierta por %s.", self.env.user.name))
        return True


class CviSupervisionLine(models.Model):
    _name = "cvi.supervision.line"
    _description = "Tarjeta revisada en una visita de supervisión"
    _order = "visit_id, id"

    visit_id = fields.Many2one(
        "cvi.supervision.visit", string="Visita", required=True,
        ondelete="cascade", index=True,
    )
    card_id = fields.Many2one(
        "cvi.card", string="Tarjeta", required=True, ondelete="cascade", index=True,
    )
    partner_id = fields.Many2one(
        related="card_id.partner_id", store=True, string="Cliente",
    )
    amount_residual = fields.Monetary(
        related="card_id.amount_residual", string="Saldo",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(related="card_id.currency_id", readonly=True)
    company_id = fields.Many2one(
        related="visit_id.company_id", store=True, index=True,
    )
    verified = fields.Boolean(string="Verificada", default=False)
    has_issue = fields.Boolean(string="Con observación", default=False)
    note = fields.Char(string="Observación")

    @api.constrains("has_issue", "note")
    def _check_issue_has_note(self):
        """Una observación sin texto no le sirve a nadie que lea la visita después."""
        for line in self:
            if line.has_issue and not line.note:
                raise ValidationError(_(
                    "La tarjeta %s está marcada con observación pero no dice cuál.",
                    line.card_id.name,
                ))
