# -*- coding: utf-8 -*-
import calendar
import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero
from werkzeug.urls import url_encode

from .cvi_product_plan import FREQUENCY_SELECTION

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("sold", "Vendida"),
    ("routed", "Enrutada"),
    ("active", "En cobranza"),
    ("done", "Finalizada"),
    ("recovered", "Retirada"),
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

# amount_total queda afuera a propósito: se calcula desde las líneas, así que
# protegerlo sería redundante y rompería el propio recálculo.
CVI_FROZEN_FIELDS = (
    "line_ids",
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
    customer_id = fields.Many2one(
        "cvi.customer",
        string="Cliente",
        required=True,
        tracking=True,
        index=True,
        ondelete="restrict",
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
    line_ids = fields.One2many(
        "cvi.card.line", "card_id", string="Mercadería", copy=True,
    )
    # Los tres campos siguientes son de la PRIMERA línea. Existen para que las listas,
    # los filtros y el código que venía de la venta de un solo mueble sigan andando;
    # la fuente de verdad son las líneas. El create() traduce la terna vieja en una
    # línea, así que cargar una venta de un solo mueble sigue funcionando igual.
    product_id = fields.Many2one(
        "product.product", string="Modelo de mueble",
        compute="_compute_from_lines", store=True, index=True,
    )
    product_tmpl_id = fields.Many2one(
        related="product_id.product_tmpl_id", string="Ficha del mueble", readonly=True
    )
    plan_id = fields.Many2one(
        "cvi.product.plan", string="Plan de cuotas",
        compute="_compute_from_lines", store=True,
    )
    quantity = fields.Float(
        string="Cantidad", compute="_compute_from_lines", store=True,
    )
    line_count = fields.Integer(
        string="Muebles", compute="_compute_from_lines", store=True,
    )
    date_sale = fields.Date(
        string="Fecha de venta",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    # Fotos que el vendedor saca en el domicilio (HU-08). Opcionales: la venta se
    # confirma sin ellas.
    #
    # max_width/max_height hacen que Odoo redimensione al guardar. Sin eso, cada foto de
    # un celular moderno entra al filestore con varios megas: dos por venta, miles de
    # ventas. 1600 px alcanza de sobra para leer un documento o reconocer una casa.
    photo_dni = fields.Image(
        string="Foto del DNI",
        max_width=1600,
        max_height=1600,
        copy=False,
        help="Documento del cliente. Opcional.",
    )
    photo_house = fields.Image(
        string="Foto de la vivienda",
        max_width=1600,
        max_height=1600,
        copy=False,
        help="Fachada del domicilio, para que el cobrador la reconozca. Opcional.",
    )
    # HU-28: la alerta advierte, no bloquea. Fue decisión del cliente cuando se
    # planificó el MVP (punto abierto 8 del spec).
    partner_alert = fields.Text(
        string="Antecedentes del cliente",
        compute="_compute_partner_alert",
    )
    partner_history_ids = fields.Many2many(
        "cvi.card",
        "cvi_card_history_rel", "card_id", "history_id",
        string="Compras anteriores",
        compute="_compute_partner_alert",
        help="Tarjetas previas del mismo cliente, incluidas las cargadas con otro "
             "nombre pero el mismo DNI (HU-29).",
    )
    has_partner_alert = fields.Boolean(
        string="Tiene antecedentes", compute="_compute_partner_alert",
    )
    has_photos = fields.Boolean(
        string="Tiene fotos",
        compute="_compute_has_photos",
        store=True,
    )
    # Coordenadas tomadas del GPS del dispositivo en el momento de cargar la venta
    # (HU-07). No salen de la dirección del contacto: en estos barrios la dirección
    # nominal suele no coincidir con dónde está realmente la casa.
    cvi_latitude = fields.Float(string="Latitud", digits=(10, 7), copy=False)
    cvi_longitude = fields.Float(string="Longitud", digits=(10, 7), copy=False)
    cvi_geo_accuracy = fields.Float(
        string="Precisión (m)",
        digits=(6, 1),
        copy=False,
        help="Radio de error que informó el GPS del dispositivo, en metros.",
    )
    cvi_geo_date = fields.Datetime(
        string="Ubicación tomada el",
        readonly=True,
        copy=False,
        help="Se completa sola cada vez que se graban coordenadas nuevas.",
    )
    has_geolocation = fields.Boolean(
        string="Tiene ubicación GPS",
        compute="_compute_has_geolocation",
        store=True,
    )
    map_url = fields.Char(string="Mapa", compute="_compute_map_url")
    # No es CVI_FROZEN_FIELDS a propósito: se carga después de confirmar la venta.
    date_first_payment = fields.Date(
        string="Fecha de cobro de la entrega",
        tracking=True,
        copy=False,
        help="Día en que el vendedor cobró la primera cuota. Puede ser distinto al de "
             "la venta. Si se deja vacío, se toma el día en que se registre el cobro.",
    )
    first_installment_paid = fields.Boolean(
        string="Entrega cobrada",
        compute="_compute_first_installment_paid",
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
    # Mora y recupero (E7). "A retirar" es una marca y no un estado porque la tarjeta
    # sigue en cobranza mientras tanto: si el cliente aparece y paga, se salva.
    # "Retirada" sí es un estado: ahí la cobranza termina (HU-25, HU-26).
    to_recover = fields.Boolean(
        string="A retirar", default=False, copy=False, tracking=True,
        help="Marcada para recuperar la mercadería (HU-25).",
    )
    to_recover_reason = fields.Char(string="Motivo del retiro", copy=False)
    to_recover_date = fields.Datetime(string="Marcada el", readonly=True, copy=False)
    to_recover_user_id = fields.Many2one(
        "res.users", string="Marcada por", readonly=True, copy=False,
    )
    amount_paid_at_recovery = fields.Monetary(
        string="Cobrado hasta el retiro", readonly=True, copy=False,
        currency_field="currency_id",
        help="Cuánto había pagado el cliente cuando se retiró el mueble (HU-26).",
    )
    recovery_picking_id = fields.Many2one(
        "stock.picking", string="Albarán de retiro", readonly=True, copy=False,
    )
    days_overdue = fields.Integer(
        string="Días de atraso", compute="_compute_overdue_info", store=True,
        help="Días desde el vencimiento de la cuota impaga más vieja (HU-24).",
    )
    amount_overdue = fields.Monetary(
        string="Deuda vencida", compute="_compute_overdue_info", store=True,
        currency_field="currency_id",
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

    # Los computes van uno por campo a propósito: la protección de Odoo contra pisar
    # valores explícitos es a nivel de MÉTODO, así que uno compartido se saltearía
    # entero cuando el create trae solo uno de los campos.
    @api.depends("line_ids.product_id", "line_ids.plan_id", "line_ids.quantity")
    def _compute_from_lines(self):
        """Refleja la primera línea, para las vistas y los filtros que venían de antes."""
        for card in self:
            first = card.line_ids[:1]
            card.product_id = first.product_id
            card.plan_id = first.plan_id
            card.quantity = sum(card.line_ids.mapped("quantity"))
            card.line_count = len(card.line_ids)

    @api.depends("line_ids.installment_count")
    def _compute_installment_count(self):
        """Largo del calendario: el plazo de la línea que más tarda (HU-05)."""
        for card in self:
            counts = card.line_ids.mapped("installment_count")
            card.installment_count = (
                max(counts) if counts else card.company_id.cvi_default_installments
            )

    @api.depends("line_ids.amount_per_installment")
    def _compute_installment_amount(self):
        """Importe de la PRIMERA cuota, que es la más alta (HU-05).

        Con varias líneas las cuotas dejan de ser todas iguales: a medida que cada plan
        se termina, la cuota baja. Este es el número que el vendedor pronuncia en la
        calle, no un valor uniforme del calendario.
        """
        for card in self:
            card.installment_amount = sum(
                card.line_ids.mapped("amount_per_installment")
            )

    @api.depends("line_ids.frequency")
    def _compute_frequency(self):
        """Modalidad de cobro. Todas las líneas comparten frecuencia (HU-06)."""
        for card in self:
            frequencies = set(card.line_ids.mapped("frequency"))
            card.frequency = frequencies.pop() if len(frequencies) == 1 else "monthly"

    @api.depends("line_ids.amount_subtotal")
    def _compute_amount_total(self):
        """Suma de los subtotales de las líneas. Nunca se carga a mano."""
        for card in self:
            card.amount_total = sum(card.line_ids.mapped("amount_subtotal"))

    @api.depends("frequency", "charge_day_month", "charge_day_week")
    def _compute_charge_day_display(self):
        """Texto legible del día de cobro, para listas y para el cobrador."""
        for card in self:
            if card.frequency == "weekly":
                day = WEEKDAY_PLURAL.get(card.charge_day_week, "")
                card.charge_day_display = _("Todos los %s", day) if day else ""
            else:
                card.charge_day_display = _("Día %s de cada mes", card.charge_day_month)

    @api.constrains("line_ids")
    def _check_single_frequency(self):
        """Todas las líneas comparten frecuencia.

        Una tarjeta que cobrara parte mensual y parte semanal no tendría un calendario
        único: cada cuota necesita una fecha, y dos ritmos dan dos calendarios.
        """
        for card in self:
            frequencies = set(card.line_ids.mapped("frequency"))
            if len(frequencies) > 1:
                raise ValidationError(_(
                    "La tarjeta %(card)s mezcla planes mensuales y semanales. Todos "
                    "los muebles de una venta tienen que cobrarse con la misma "
                    "frecuencia.",
                    card=card.name,
                ))

    @api.constrains("line_ids", "state")
    def _check_has_lines(self):
        """Una venta confirmada sin mercadería no es una venta."""
        for card in self:
            if card.state not in ("draft", "cancel") and not card.line_ids:
                raise ValidationError(_(
                    "La tarjeta %s no tiene ningún mueble cargado.", card.name
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

    # Campos de la terna vieja que se aceptan en el create como atajo de una línea.
    _CVI_SINGLE_LINE_KEYS = ("product_id", "plan_id", "quantity")

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna la referencia y admite la carga de un solo mueble sin líneas.

        product_id, plan_id y quantity son calculados desde las líneas, así que pasarlos
        al create no crearía nada. Se los traduce en una línea: así una venta de un solo
        mueble se sigue cargando como siempre, y el código que ya existía no se rompe.
        """
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cvi.card") or _("Nuevo")
            if not vals.get("line_ids") and vals.get("product_id") and vals.get("plan_id"):
                line = {
                    "product_id": vals.pop("product_id"),
                    "plan_id": vals.pop("plan_id"),
                    "quantity": vals.pop("quantity", 1.0),
                }
                for key in ("installment_count", "installment_amount", "frequency"):
                    if key in vals:
                        line[key] = vals.pop(key)
                vals["line_ids"] = [(0, 0, line)]
            else:
                for key in self._CVI_SINGLE_LINE_KEYS:
                    vals.pop(key, None)
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

        El importe de cada cuota es la suma de lo que aporta cada línea que todavía
        tiene cuotas pendientes en ese período. No hay resto que repartir: el total
        sale de los planes, nunca de una división.
        """
        self.ensure_one()
        self.installment_ids.unlink()
        due_dates = [self.date_sale] + self._cvi_due_dates(self.installment_count - 1)
        vals_list = []
        for index, due in enumerate(due_dates, start=1):
            # Cada línea aporta a las cuotas 1..N de SU plan. Cuando un plan corto se
            # termina, deja de sumar y la cuota baja: por eso las cuotas no son todas
            # iguales cuando la venta tiene muebles con planes distintos.
            amount = sum(
                line.amount_per_installment
                for line in self.line_ids
                if index <= line.installment_count
            )
            if not amount:
                continue
            vals_list.append({
                "card_id": self.id,
                "sequence": index,
                "date_due": due,
                "amount": amount,
                "is_commission": index == 1,
            })
        self.env["cvi.installment"].create(vals_list)
        return True

    def write(self, vals):
        """Congela precio, cuotas y mercadería una vez confirmada la venta (RN-05).

        También sella cvi_geo_date: la fecha de la ubicación se pone acá y no en el
        cliente, para que valga sin importar quién grabe las coordenadas.
        """
        coords = ("cvi_latitude", "cvi_longitude")
        if any(name in vals for name in coords) and "cvi_geo_date" not in vals:
            # Poner las coordenadas en cero es borrarlas (ver action_clear_geolocation):
            # eso no es una toma nueva y no debe sellar fecha.
            if any(vals.get(name) for name in coords):
                vals = dict(vals, cvi_geo_date=fields.Datetime.now())
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

    @api.depends("customer_id")
    def _compute_partner_alert(self):
        """Antecedentes del cliente al que se le está por vender (HU-28, HU-29).

        Con el DNI como identidad no hay que cruzar homónimos: si es el mismo
        documento es el mismo cliente, así que los antecedentes son los suyos.
        Advierte y no bloquea, por decisión del cliente.
        """
        for card in self:
            card.partner_alert = False
            card.partner_history_ids = False
            card.has_partner_alert = False
            if not card.customer_id:
                continue
            card.partner_history_ids = self.sudo().search([
                ("customer_id", "=", card.customer_id.id),
                ("id", "!=", card.id or 0),
                ("state", "not in", ("draft", "cancel")),
            ])
            avisos = card.customer_id._cvi_alerts()
            if avisos:
                card.partner_alert = "\n".join(avisos)
                card.has_partner_alert = True

    @api.depends("photo_dni", "photo_house")
    def _compute_has_photos(self):
        """Si la venta tiene alguna de las dos fotos cargadas."""
        for card in self:
            card.has_photos = bool(card.photo_dni or card.photo_house)

    @api.depends("cvi_latitude", "cvi_longitude")
    def _compute_has_geolocation(self):
        """Una venta tiene ubicación cuando el GPS dejó coordenadas distintas de cero.

        (0, 0) es el punto nulo en medio del Atlántico: en la práctica significa que el
        campo nunca se completó, no que la venta ocurrió ahí.
        """
        for card in self:
            card.has_geolocation = bool(card.cvi_latitude or card.cvi_longitude)

    @api.depends("cvi_latitude", "cvi_longitude")
    def _compute_map_url(self):
        """Link al mapa con las coordenadas tomadas al vender (HU-07)."""
        for card in self:
            if card.has_geolocation:
                query = url_encode({
                    "api": "1",
                    "query": "%s,%s" % (card.cvi_latitude, card.cvi_longitude),
                })
                card.map_url = "https://www.google.com/maps/search/?%s" % query
            else:
                card.map_url = False

    def action_open_map(self):
        """Abre en el mapa el punto donde se cargó la venta (HU-07)."""
        self.ensure_one()
        if not self.map_url:
            raise UserError(_(
                "La venta %s no tiene ubicación GPS registrada.", self.name
            ))
        return {"type": "ir.actions.act_url", "url": self.map_url, "target": "new"}

    def action_clear_geolocation(self):
        """Borra las coordenadas para poder volver a tomarlas."""
        self.ensure_one()
        self.write({
            "cvi_latitude": 0.0,
            "cvi_longitude": 0.0,
            "cvi_geo_accuracy": 0.0,
            "cvi_geo_date": False,
        })
        self._cvi_log(_("Ubicación GPS borrada por %s.", self.env.user.name))
        return True

    @api.depends("installment_ids.is_commission", "installment_ids.state")
    def _compute_first_installment_paid(self):
        """Si la primera cuota, la que cobra el vendedor, ya está saldada."""
        for card in self:
            first = card.installment_ids.filtered(lambda i: i.is_commission)
            card.first_installment_paid = bool(first) and first[0].state == "paid"

    def action_open_first_payment_wizard(self):
        """Abre el asistente para cobrar la entrega, con su monto ya cargado (HU-09).

        La entrega también puede pagarse en partes, así que el vendedor tiene que poder
        corregir el monto antes de registrarlo.
        """
        self.ensure_one()
        if self.state in ("draft", "cancel"):
            raise UserError(_(
                "Confirmá la venta de %s antes de registrar el cobro de la entrega.",
                self.name,
            ))
        first = self.installment_ids.filtered(lambda i: i.is_commission)
        if not first:
            raise UserError(_(
                "La tarjeta %s no tiene primera cuota generada.", self.name
            ))
        return first[0].action_register_payment()

    def action_charge_first_installment(self, amount=None, date=None):
        """Registra el cobro de la primera cuota, que se lleva el vendedor (RN-01, HU-09).

        No se dispara al confirmar la venta: el vendedor cobra la entrega cuando
        efectivamente la cobra, que puede ser otro día. La fecha sale de
        date_first_payment; si está vacía se usa hoy y se deja registrada.

        Sin monto cobra lo que falta de la entrega. Con monto cobra eso: la entrega
        también se paga en partes, y el resto queda pendiente en la misma cuota.
        """
        self.ensure_one()
        if self.state in ("draft", "cancel"):
            raise UserError(_(
                "Confirmá la venta de %s antes de registrar el cobro de la entrega.",
                self.name,
            ))
        first = self.installment_ids.filtered(lambda i: i.is_commission)
        if not first:
            raise UserError(_(
                "La tarjeta %s no tiene primera cuota generada.", self.name
            ))
        if first[0].state == "paid":
            raise UserError(_(
                "La entrega de %s ya fue cobrada.", self.name
            ))
        if date:
            self.date_first_payment = date
        if not self.date_first_payment:
            self.date_first_payment = fields.Date.context_today(self)
        payment = self.env["cvi.payment"].create({
            "card_id": self.id,
            "date": self.date_first_payment,
            "amount": amount or first[0].amount_residual,
            "user_id": self.vendor_id.id,
            "is_commission": True,
            "note": _("Primera cuota cobrada por el vendedor (comisión)."),
        })
        payment.action_post()
        self._cvi_log(_(
            "Cobro de la entrega registrado por %(user)s con fecha %(date)s.",
            user=self.env.user.name,
            date=self.date_first_payment,
        ))
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
        # Se agrupa por producto antes de chequear: dos líneas del mismo mueble se
        # descuentan del mismo stock, y mirarlas por separado dejaría pasar una venta
        # que en conjunto no tiene existencias.
        needed = {}
        for line in self.line_ids:
            needed[line.product_id] = needed.get(line.product_id, 0.0) + line.quantity
        quant = self.env["stock.quant"]
        for product, asked in needed.items():
            available = quant._get_available_quantity(product, source)
            if asked > available:
                raise UserError(_(
                    "%(vendor)s no tiene %(asked)s unidades de %(product)s a cargo "
                    "(disponibles: %(available)s). Registrá la entrega de mercadería "
                    "primero.",
                    vendor=self.vendor_id.name,
                    asked=asked,
                    product=product.display_name,
                    available=available,
                ))
        # El vendedor no es operario de depósito y no debe recibir el grupo completo de
        # Inventario: el albarán es una consecuencia interna de una acción que ya está
        # autorizado a hacer. El chequeo de disponibilidad de arriba corre como el
        # usuario real; solo el alta y validación del albarán van con sudo.
        picking = self.env["stock.picking"].sudo().create({
            "picking_type_id": warehouse.out_type_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            # Sin contacto: el cliente dejó de ser un res.partner. Va en el origen,
            # que es lo que se lee en el albarán impreso.
            "origin": _("%(card)s - %(customer)s", card=self.name,
                        customer=self.customer_id.display_name),
            "move_ids": [(0, 0, {
                "name": product.display_name,
                "product_id": product.id,
                "product_uom_qty": asked,
                "product_uom": product.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
            }) for product, asked in needed.items()],
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
        """Confirma la venta: descuenta stock y genera las cuotas.

        No cobra la primera cuota: eso lo hace el vendedor a mano con
        action_charge_first_installment, porque puede cobrarla otro día.
        """
        for card in self:
            if card.state != "draft":
                raise UserError(_(
                    "La tarjeta %(card)s ya fue confirmada (estado: %(state)s).",
                    card=card.name,
                    state=dict(STATE_SELECTION)[card.state],
                ))
            card._cvi_create_sale_picking()
            card._cvi_generate_installments()
            card.state = "routed" if card.collector_id else "sold"
            card._cvi_log(_(
                "Venta confirmada por %(user)s: %(count)s cuotas de %(amount)s.",
                user=card.vendor_id.name,
                count=card.installment_count,
                amount=card.installment_amount,
            ))
        return True

    @api.depends(
        "installment_ids.state",
        "installment_ids.date_due",
        "installment_ids.amount_residual",
    )
    def _compute_overdue_info(self):
        """Antigüedad y monto de la deuda vencida, para el listado de morosos (HU-24)."""
        today = fields.Date.context_today(self)
        for card in self:
            overdue = card.installment_ids.filtered(
                lambda i: i.state == "overdue" and not i.is_commission
            )
            card.amount_overdue = sum(overdue.mapped("amount_residual"))
            if overdue:
                oldest = min(overdue.mapped("date_due"))
                card.days_overdue = (today - oldest).days
            else:
                card.days_overdue = 0

    def action_mark_to_recover(self):
        """Marca la tarjeta para recuperar la mercadería (HU-25).

        Es una marca y no un estado: la tarjeta sigue en cobranza. Si el cliente
        aparece y paga antes del retiro, se salva sin tener que deshacer nada.
        """
        self.ensure_one()
        if self.state not in ("active", "routed"):
            raise UserError(_(
                "Solo se marca para retiro una tarjeta en cobranza. %(card)s está en "
                "%(state)s.",
                card=self.name, state=dict(STATE_SELECTION)[self.state],
            ))
        if self.to_recover:
            raise UserError(_("La tarjeta %s ya está marcada para retiro.", self.name))
        if not self.to_recover_reason:
            raise UserError(_(
                "Cargá el motivo antes de marcar %s para retiro.", self.name
            ))
        self.write({
            "to_recover": True,
            "to_recover_date": fields.Datetime.now(),
            "to_recover_user_id": self.env.user.id,
        })
        self._cvi_log(_(
            "Tarjeta marcada PARA RETIRO por %(user)s. Motivo: %(reason)s.",
            user=self.env.user.name, reason=self.to_recover_reason,
        ))
        return True

    def action_unmark_to_recover(self):
        """Levanta la marca de retiro, por ejemplo si el cliente se puso al día."""
        self.ensure_one()
        if not self.to_recover:
            raise UserError(_("La tarjeta %s no está marcada para retiro.", self.name))
        self.write({"to_recover": False, "to_recover_date": False,
                    "to_recover_user_id": False})
        self._cvi_log(_("Marca de retiro levantada por %s.", self.env.user.name))
        return True

    def action_register_recovery(self):
        """Registra que el mueble se retiró y cierra la cobranza (HU-26).

        Deja asentado cuánto había pagado el cliente hasta ese momento: es el dato que
        después se discute, y las cuotas quedan impagas para siempre.
        """
        self.ensure_one()
        if not self.to_recover:
            raise UserError(_(
                "Marcá %s para retiro antes de registrar la recuperación.", self.name
            ))
        if self.state == "recovered":
            raise UserError(_("El mueble de %s ya fue retirado.", self.name))
        picking = self._cvi_create_recovery_picking()
        self.write({
            "state": "recovered",
            "amount_paid_at_recovery": self.amount_paid,
            "recovery_picking_id": picking.id,
        })
        self._cvi_log(_(
            "Mueble RETIRADO por %(user)s. El cliente había pagado %(paid)s de "
            "%(total)s. Albarán %(picking)s.",
            user=self.env.user.name,
            paid=self.amount_paid,
            total=self.amount_total,
            picking=picking.name,
        ))
        _logger.info(
            "Tarjeta %s retirada: cobrado %s de %s",
            self.name, self.amount_paid, self.amount_total,
        )
        return True

    def _cvi_create_recovery_picking(self):
        """Reingresa la unidad retirada a la ubicación de recuperados (HU-26).

        No vuelve al stock vendible: un mueble usado no es el mismo producto que uno
        nuevo, y mezclarlos falsearía la disponibilidad de fábrica.
        """
        self.ensure_one()
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        if not warehouse:
            raise UserError(_(
                "No hay un almacén configurado para la empresa %s.", self.company_id.name
            ))
        source = self.env.ref("stock.stock_location_customers")
        destination = self.env.ref(
            "collections_from_vendors_installments.stock_location_recovered"
        )
        # Mismo criterio que la venta: el administrador no es operario de depósito.
        picking = self.env["stock.picking"].sudo().create({
            "picking_type_id": warehouse.in_type_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "origin": _("Retiro de %(card)s - %(customer)s", card=self.name,
                        customer=self.customer_id.display_name),
            "move_ids": [(0, 0, {
                "name": line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": line.quantity,
                "product_uom": line.product_id.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
            }) for line in self.line_ids],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        if picking.state != "done":
            raise UserError(_(
                "No se pudo validar el albarán de retiro de %(card)s: quedó en "
                "%(state)s.",
                card=self.name, state=picking.state,
            ))
        return picking

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
        """El cobrador acepta las tarjetas enrutadas y se hace responsable (RN-02, HU-12).

        Trabaja sobre todo el recordset: desde la lista de pendientes se aceptan varias
        de una vez, sin abrir una por una. Si alguna no corresponde no se acepta ninguna,
        porque la excepción revierte la transacción entera.
        """
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
        # El aviso confirma cuántas entraron a la cartera. Sin él, aceptar en lote es
        # una lista que se vacía sin explicar qué pasó. El next fuerza el refresco.
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("%s tarjetas aceptadas: ya están en tu cartera.", len(self))
                if len(self) > 1
                else _("Tarjeta aceptada: ya está en tu cartera."),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

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
