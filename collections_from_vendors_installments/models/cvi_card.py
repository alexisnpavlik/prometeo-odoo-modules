# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .cvi_product_plan import FREQUENCY_SELECTION

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("sold", "Vendida"),
    ("routed", "Enrutada"),
    ("active", "En cobranza"),
    ("done", "Finalizada"),
    ("cancel", "Anulada"),
]

WEEKDAY_SELECTION = [
    ("0", "Lunes"),
    ("1", "Martes"),
    ("2", "Miércoles"),
    ("3", "Jueves"),
    ("4", "Viernes"),
    ("5", "Sábado"),
    ("6", "Domingo"),
]

WEEKDAY_PLURAL = {
    "0": "lunes",
    "1": "martes",
    "2": "miércoles",
    "3": "jueves",
    "4": "viernes",
    "5": "sábados",
    "6": "domingos",
}


class CviCard(models.Model):
    _name = "cvi.card"
    _description = "Tarjeta de venta domiciliaria en cuotas"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_sale desc, id desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("Nuevo"),
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Moneda",
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Cliente",
        required=True,
        tracking=True,
        index=True,
    )
    vendor_id = fields.Many2one(
        "res.users",
        string="Vendedor",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
        index=True,
    )
    collector_id = fields.Many2one(
        "res.users",
        string="Cobrador",
        tracking=True,
        index=True,
        copy=False,
        help="En estado Enrutada es el destinatario pendiente de aceptar; "
             "en En cobranza es el responsable de la cobranza.",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Modelo de mueble",
        required=True,
        domain="[('is_storable', '=', True)]",
    )
    product_tmpl_id = fields.Many2one(
        related="product_id.product_tmpl_id", string="Ficha del mueble", readonly=True
    )
    plan_id = fields.Many2one(
        "cvi.product.plan",
        string="Plan de cuotas",
        required=True,
        tracking=True,
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        help="Los planes se definen en la ficha del mueble, pestaña Planes de cuotas.",
    )
    quantity = fields.Float(string="Cantidad", default=1.0, required=True)
    date_sale = fields.Date(
        string="Fecha de venta",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    installment_count = fields.Integer(
        string="Cantidad de cuotas",
        compute="_compute_installment_count",
        store=True,
        readonly=False,
        tracking=True,
    )
    installment_amount = fields.Monetary(
        string="Importe de cuota",
        compute="_compute_installment_amount",
        store=True,
        readonly=False,
        currency_field="currency_id",
        tracking=True,
    )
    frequency = fields.Selection(
        selection=FREQUENCY_SELECTION,
        string="Frecuencia",
        compute="_compute_frequency",
        store=True,
        readonly=False,
        tracking=True,
    )
    amount_total = fields.Monetary(
        string="Precio total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
        tracking=True,
        help="Cantidad de cuotas por importe de cuota. No se carga a mano.",
    )
    charge_day_month = fields.Integer(
        string="Día del mes",
        default=lambda self: fields.Date.context_today(self).day,
        help="Día de cobro cuando la frecuencia es mensual. Si el mes no llega a ese día, se cobra el último.",
    )
    charge_day_week = fields.Selection(
        selection=WEEKDAY_SELECTION,
        string="Día de la semana",
        default="0",
        help="Día de cobro cuando la frecuencia es semanal.",
    )
    charge_day_display = fields.Char(
        string="Día de cobro",
        compute="_compute_charge_day_display",
        store=True,
    )
    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Estado",
        default="draft",
        required=True,
        copy=False,
        tracking=True,
        index=True,
    )

    _sql_constraints = [
        (
            "amount_total_positive",
            "CHECK(amount_total > 0)",
            "El precio total de la venta debe ser mayor a cero.",
        ),
    ]

    @api.depends("plan_id")
    def _compute_installment_count(self):
        """Cantidad de cuotas del plan elegido (HU-05)."""
        for card in self:
            if card.plan_id:
                card.installment_count = card.plan_id.installment_count
            else:
                card.installment_count = card.company_id.cvi_default_installments

    @api.depends("plan_id")
    def _compute_installment_amount(self):
        """Importe de cuota del plan elegido, con el interés ya incluido (HU-05)."""
        for card in self:
            card.installment_amount = card.plan_id.installment_amount if card.plan_id else 0.0

    @api.depends("plan_id")
    def _compute_frequency(self):
        """Modalidad de cobro del plan elegido (HU-06)."""
        for card in self:
            card.frequency = card.plan_id.frequency if card.plan_id else "monthly"

    @api.depends("installment_count", "installment_amount")
    def _compute_amount_total(self):
        """El precio total de la venta es cuotas por importe: nunca se carga a mano."""
        for card in self:
            card.amount_total = card.installment_count * card.installment_amount

    @api.depends("frequency", "charge_day_month", "charge_day_week")
    def _compute_charge_day_display(self):
        """Texto legible del día de cobro, para listas y para el cobrador."""
        for card in self:
            if card.frequency == "weekly":
                day = WEEKDAY_PLURAL.get(card.charge_day_week, "")
                card.charge_day_display = _("Todos los %s", day) if day else ""
            else:
                card.charge_day_display = _("Día %s de cada mes", card.charge_day_month)

    @api.constrains("plan_id", "product_id")
    def _check_plan_belongs_to_product(self):
        """El plan elegido tiene que ser uno de los cargados en la ficha de ese mueble."""
        for card in self:
            if card.plan_id.product_tmpl_id != card.product_id.product_tmpl_id:
                raise ValidationError(_(
                    "El plan %(plan)s pertenece a %(plan_product)s, no a %(product)s.",
                    plan=card.plan_id.name,
                    plan_product=card.plan_id.product_tmpl_id.display_name,
                    product=card.product_id.display_name,
                ))

    @api.constrains("plan_id", "installment_count", "installment_amount", "frequency")
    def _check_plan_values(self):
        """Solo el administrador puede vender con valores distintos a los del plan (RN-05)."""
        if self.env.user.has_group(
            "collections_from_vendors_installments.group_cvi_manager"
        ):
            return
        for card in self:
            plan = card.plan_id
            currency = card.currency_id
            differs = (
                card.installment_count != plan.installment_count
                or currency.compare_amounts(
                    card.installment_amount, plan.installment_amount
                ) != 0
                or card.frequency != plan.frequency
            )
            if differs:
                raise ValidationError(_(
                    "El plan %(plan)s se vende en %(count)s cuotas de %(amount)s. "
                    "Solo un administrador puede vender con otros valores.",
                    plan=plan.name,
                    count=plan.installment_count,
                    amount=plan.installment_amount,
                ))

    @api.constrains("frequency", "charge_day_month", "charge_day_week")
    def _check_charge_day(self):
        """El día de cobro debe ser válido para la frecuencia del plan."""
        for card in self:
            if card.frequency == "monthly" and not 1 <= card.charge_day_month <= 31:
                raise ValidationError(_(
                    "El día de cobro mensual debe estar entre 1 y 31 (recibido: %s).",
                    card.charge_day_month,
                ))
            if card.frequency == "weekly" and not card.charge_day_week:
                raise ValidationError(_("Elegí el día de la semana en que se cobra."))

    @api.constrains("frequency", "company_id")
    def _check_frequency_allowed(self):
        """La frecuencia del plan tiene que estar habilitada en la configuración (HU-31)."""
        for card in self:
            allowed = card.company_id.cvi_allowed_frequencies
            if allowed != "both" and card.frequency != allowed:
                raise ValidationError(_(
                    "La empresa %(company)s solo permite ventas con frecuencia %(allowed)s.",
                    company=card.company_id.name,
                    allowed=dict(
                        card.company_id._fields["cvi_allowed_frequencies"].selection
                    )[allowed],
                ))

    @api.constrains("installment_count")
    def _check_installment_count(self):
        """No tiene sentido una venta con cero o menos cuotas."""
        for card in self:
            if card.installment_count < 1:
                raise ValidationError(_("La cantidad de cuotas debe ser al menos 1."))

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Al cambiar de mueble, el plan anterior deja de corresponder."""
        if self.plan_id.product_tmpl_id != self.product_id.product_tmpl_id:
            self.plan_id = False

    @api.onchange("frequency")
    def _onchange_frequency(self):
        """Al pasar a semanal, hay que elegir día de la semana en vez de día del mes."""
        if self.frequency == "weekly" and not self.charge_day_week:
            self.charge_day_week = str(fields.Date.context_today(self).weekday())

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna la referencia desde la secuencia al crear."""
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cvi.card") or _("Nuevo")
        return super().create(vals_list)
