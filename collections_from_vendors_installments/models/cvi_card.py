# -*- coding: utf-8 -*-
import calendar
import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

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

CVI_FROZEN_FIELDS = (
    "plan_id",
    "installment_count",
    "installment_amount",
    "frequency",
    "product_id",
    "quantity",
)


class CviCard(models.Model):
    _name = "cvi.card"
    _description = "Tarjeta de venta domiciliaria en cuotas"
    _inherit = ["mail.thread", "mail.activity.mixin", "cvi.audit.mixin"]
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
    reject_reason = fields.Char(
        string="Motivo del rechazo",
        readonly=True,
        copy=False,
        help="Motivo por el que el cobrador devolvió la tarjeta al vendedor.",
    )
    picking_id = fields.Many2one(
        "stock.picking",
        string="Albarán de venta",
        readonly=True,
        copy=False,
        help="Albarán que descontó el mueble del stock del vendedor al confirmar la venta.",
    )
    installment_ids = fields.One2many(
        "cvi.installment", "card_id", string="Cuotas", copy=False
    )
    payment_ids = fields.One2many(
        "cvi.payment", "card_id", string="Cobros", copy=False
    )
    amount_paid = fields.Monetary(
        string="Cobrado",
        compute="_compute_balance",
        store=True,
        currency_field="currency_id",
    )
    amount_residual = fields.Monetary(
        string="Saldo",
        compute="_compute_balance",
        store=True,
        currency_field="currency_id",
    )
    paid_installment_count = fields.Integer(
        string="Cuotas pagadas", compute="_compute_balance", store=True
    )
    pending_installment_count = fields.Integer(
        string="Cuotas pendientes", compute="_compute_balance", store=True
    )
    overdue_installment_count = fields.Integer(
        string="Cuotas vencidas", compute="_compute_balance", store=True
    )
    next_due_date = fields.Date(
        string="Próximo vencimiento", compute="_compute_balance", store=True, index=True
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

    def _cvi_due_dates(self, count):
        """Vencimientos de las `count` cuotas de cobranza (las que cobra el cobrador).

        La cuota 1 no entra acá: vence el día de la venta porque la cobra el vendedor.
        Mensual: la primera cae el día de cobro del mes SIGUIENTE al de la venta,
        recortada al último día si el mes no llega (31 en febrero -> 28).
        Semanal: la primera cae en la próxima ocurrencia estricta del día elegido.
        """
        self.ensure_one()
        dates = []
        if self.frequency == "weekly":
            target = int(self.charge_day_week)
            delta = (target - self.date_sale.weekday()) % 7 or 7
            current = self.date_sale + relativedelta(days=delta)
            for _index in range(count):
                dates.append(current)
                current = current + relativedelta(days=7)
        else:
            cursor = self.date_sale + relativedelta(months=1)
            for _index in range(count):
                last_day = calendar.monthrange(cursor.year, cursor.month)[1]
                dates.append(
                    date(cursor.year, cursor.month, min(self.charge_day_month, last_day))
                )
                cursor = cursor + relativedelta(months=1)
        return dates

    def _cvi_generate_installments(self):
        """Genera el calendario completo de cuotas, reemplazando el anterior si existe.

        La cuota 1 es la comisión del vendedor y vence el día de la venta (RN-01).
        Todas las cuotas valen lo mismo: el importe que fija el plan. No hay resto que
        repartir, porque el precio total de la tarjeta es cuotas por importe.
        """
        self.ensure_one()
        self.installment_ids.unlink()
        due_dates = [self.date_sale] + self._cvi_due_dates(self.installment_count - 1)
        vals_list = [{
            "card_id": self.id,
            "sequence": index,
            "date_due": due,
            "amount": self.installment_amount,
            "is_commission": index == 1,
        } for index, due in enumerate(due_dates, start=1)]
        self.env["cvi.installment"].create(vals_list)
        return True

    def write(self, vals):
        """Congela precio, cuotas y mercadería una vez confirmada la venta (RN-05)."""
        frozen = [name for name in CVI_FROZEN_FIELDS if name in vals]
        if frozen:
            locked = self.filtered(lambda c: c.state not in ("draft", "cancel"))
            if locked:
                labels = ", ".join(self._fields[name].string for name in frozen)
                raise UserError(_(
                    "No se puede modificar %(fields)s en la tarjeta %(card)s: "
                    "la venta ya está confirmada.",
                    fields=labels,
                    card=locked[0].name,
                ))
        return super().write(vals)

    def _cvi_charge_commission(self):
        """Registra el cobro de la primera cuota, que se lleva el vendedor (RN-01, HU-09)."""
        self.ensure_one()
        first = self.installment_ids.filtered(lambda i: i.is_commission)
        payment = self.env["cvi.payment"].create({
            "card_id": self.id,
            "date": self.date_sale,
            "amount": first.amount,
            "user_id": self.vendor_id.id,
            "is_commission": True,
            "note": _("Primera cuota cobrada por el vendedor (comisión)."),
        })
        payment.action_post()
        return payment

    def _cvi_create_sale_picking(self):
        """Descuenta el mueble vendido del stock del vendedor hacia el cliente.

        Usa el tipo de operación de salida del almacén forzando la ubicación origen a la
        del vendedor: la mercadería sale de la calle, no del depósito.
        """
        self.ensure_one()
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        if not warehouse:
            raise UserError(_(
                "No hay un almacén configurado para la empresa %s.", self.company_id.name
            ))
        source = self.vendor_id._cvi_get_location()
        destination = self.env.ref("stock.stock_location_customers")
        available = self.env["stock.quant"]._get_available_quantity(self.product_id, source)
        if self.quantity > available:
            raise UserError(_(
                "%(vendor)s no tiene %(asked)s unidades de %(product)s a cargo "
                "(disponibles: %(available)s). Registrá la entrega de mercadería primero.",
                vendor=self.vendor_id.name,
                asked=self.quantity,
                product=self.product_id.display_name,
                available=available,
            ))
        picking = self.env["stock.picking"].create({
            "picking_type_id": warehouse.out_type_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "partner_id": self.partner_id.id,
            "origin": self.name,
            "move_ids": [(0, 0, {
                "name": self.product_id.display_name,
                "product_id": self.product_id.id,
                "product_uom_qty": self.quantity,
                "product_uom": self.product_id.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        # button_validate() puede devolver un wizard de backorder en lugar de dejar
        # el albarán en "done" (aunque hoy no debería pasar: cantidad completa y
        # producto sin trazabilidad). No lo damos por hecho: si no quedó validado,
        # no hay que confirmar la venta como si el mueble ya hubiera salido.
        if picking.state != "done":
            raise UserError(_(
                "No se pudo validar el albarán de la venta %(card)s: quedó en estado "
                "%(state)s. Revisá el stock de %(vendor)s antes de confirmar.",
                card=self.name,
                state=picking.state,
                vendor=self.vendor_id.name,
            ))
        self.picking_id = picking
        return picking

    def action_confirm(self):
        """Confirma la venta: descuenta stock, genera las cuotas y cobra la comisión."""
        for card in self:
            if card.state != "draft":
                raise UserError(_(
                    "La tarjeta %(card)s ya fue confirmada (estado: %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            card._cvi_create_sale_picking()
            card._cvi_generate_installments()
            card._cvi_charge_commission()
            card.state = "routed" if card.collector_id else "sold"
            card._cvi_log(_(
                "Venta confirmada por %(user)s: %(count)s cuotas de %(amount)s.",
                user=card.vendor_id.name,
                count=card.installment_count,
                amount=card.installment_amount,
            ))
        return True

    def action_cancel(self):
        """Anula la tarjeta. Solo desde borrador o vendida, antes de entrar en cobranza."""
        for card in self:
            if card.state not in ("draft", "sold"):
                raise UserError(_(
                    "La tarjeta %(card)s no se puede anular en estado %(state)s.",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            card.state = "cancel"
            card._cvi_log(_("Tarjeta anulada por %s.", self.env.user.name))
        return True

    @api.depends(
        "amount_total",
        "installment_ids.amount_paid",
        "installment_ids.amount_residual",
        "installment_ids.state",
        "installment_ids.date_due",
    )
    def _compute_balance(self):
        """Resume el estado de cobranza de la tarjeta a partir de sus cuotas (HU-16)."""
        for card in self:
            installments = card.installment_ids
            card.amount_paid = sum(installments.mapped("amount_paid"))
            card.amount_residual = sum(installments.mapped("amount_residual"))
            card.paid_installment_count = len(
                installments.filtered(lambda i: i.state == "paid")
            )
            card.pending_installment_count = len(
                installments.filtered(lambda i: i.state in ("pending", "partial"))
            )
            card.overdue_installment_count = len(
                installments.filtered(lambda i: i.state == "overdue")
            )
            upcoming = installments.filtered(
                lambda i: not i.is_commission and i.amount_residual > 0
            ).sorted("date_due")
            card.next_due_date = upcoming[0].date_due if upcoming else False

    def _cvi_check_settlement(self):
        """Cierra la tarjeta al saldarse y la reabre si un cobro se anula (HU-17)."""
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        settled = float_is_zero(self.amount_residual, precision_rounding=rounding)
        if settled and self.state in ("sold", "routed", "active"):
            self.state = "done"
            self._cvi_log(_("Tarjeta saldada: pasa a Finalizada."))
        elif not settled and self.state == "done":
            self.state = "active"
            self._cvi_log(_(
                "La tarjeta vuelve a cobranza: quedó saldo pendiente tras anular un cobro."
            ))

    def action_route(self):
        """Envía la tarjeta al cobrador elegido, a la espera de que la acepte (HU-10)."""
        for card in self:
            if card.state != "sold":
                raise UserError(_(
                    "Solo se puede enrutar una tarjeta vendida (la tarjeta %(card)s "
                    "está en estado %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            if not card.collector_id:
                raise UserError(_(
                    "Elegí a qué cobrador enviar la tarjeta %s antes de enrutarla.",
                    card.name,
                ))
            card.state = "routed"
            card.reject_reason = False
            card._cvi_log(_(
                "Tarjeta enrutada a %(collector)s por %(user)s.",
                collector=card.collector_id.name, user=self.env.user.name,
            ))
        return True

    def action_accept(self):
        """El cobrador acepta la tarjeta enrutada y se hace responsable (RN-02, HU-12)."""
        is_manager = self.env.user.has_group(
            "collections_from_vendors_installments.group_cvi_manager"
        )
        for card in self:
            if card.state != "routed":
                raise UserError(_(
                    "Solo se puede aceptar una tarjeta enrutada (la tarjeta %(card)s "
                    "está en estado %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            if not is_manager and card.collector_id != self.env.user:
                raise UserError(_(
                    "La tarjeta %(card)s fue enrutada a %(collector)s: no la podés aceptar.",
                    card=card.name, collector=card.collector_id.name,
                ))
            card.state = "active"
            card._cvi_log(_(
                "Tarjeta aceptada por %s: se hace responsable de la cobranza.",
                card.collector_id.name,
            ))
        return True

    def action_reject(self, reason):
        """El cobrador devuelve la tarjeta al vendedor indicando un motivo (HU-13)."""
        if not reason or not reason.strip():
            raise UserError(_("Indicá el motivo del rechazo."))
        for card in self:
            if card.state != "routed":
                raise UserError(_(
                    "Solo se puede rechazar una tarjeta enrutada (la tarjeta %(card)s "
                    "está en estado %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            previous = card.collector_id
            card.state = "sold"
            card.collector_id = False
            card.reject_reason = reason.strip()
            card._cvi_log(_(
                "Tarjeta RECHAZADA por %(collector)s: %(reason)s. Vuelve al vendedor %(vendor)s.",
                collector=previous.name, reason=card.reject_reason, vendor=card.vendor_id.name,
            ))
        return True

    def action_open_reject_wizard(self):
        """Abre el wizard que pide el motivo antes de rechazar (HU-13)."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Rechazar tarjetas"),
            "res_model": "cvi.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_card_ids": [(6, 0, self.ids)]},
        }
