# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Todo lo que no sea letra o número se descarta al normalizar. El modo de falla real
# no es el error de tipeo sino el formato: 30.111.222, 30 111 222 y 30111222 son la
# misma persona, y sin normalizar entrarían como tres clientes distintos.
DNI_CLEAN_RE = re.compile(r"[^0-9A-Za-z]")


class CviCustomer(models.Model):
    _name = "cvi.customer"
    _description = "Cliente de venta domiciliaria en cuotas"
    _inherit = ["mail.thread"]
    _order = "name"
    _rec_names_search = ["name", "dni"]

    name = fields.Char(string="Nombre y apellido", required=True, tracking=True)
    dni = fields.Char(
        string="DNI", required=True, index=True, tracking=True,
        help="Documento del cliente. Es lo que identifica a la persona: se guarda "
             "sin puntos ni espacios para que un mismo DNI escrito de dos formas "
             "no cree dos clientes.",
    )
    company_id = fields.Many2one(
        "res.company", string="Empresa", required=True, index=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(string="Activo", default=True)
    mobile = fields.Char(string="Celular")
    street = fields.Char(string="Dirección")
    city_id = fields.Many2one(
        "cvi.city", string="Ciudad", index=True,
        help="Se elige de las ciudades cargadas por administración: escribirla "
             "a mano es lo que hacía entrar la misma ciudad de cinco formas.",
    )
    state_id = fields.Many2one(
        related="city_id.state_id", string="Provincia", store=True, readonly=True,
    )
    zip = fields.Char(string="Código postal")
    cvi_customer_mobile_required = fields.Boolean(
        related="company_id.cvi_customer_mobile_required",
        readonly=True,
    )
    cvi_customer_street_required = fields.Boolean(
        related="company_id.cvi_customer_street_required",
        readonly=True,
    )
    cvi_customer_city_required = fields.Boolean(
        related="company_id.cvi_customer_city_required",
        readonly=True,
    )
    cvi_customer_zip_required = fields.Boolean(
        related="company_id.cvi_customer_zip_required",
        readonly=True,
    )
    cvi_customer_dni_photos_required = fields.Boolean(
        related="company_id.cvi_customer_dni_photos_required",
        readonly=True,
    )

    # Frente y dorso del documento, en la ficha del cliente y no en la venta: el DNI es
    # de la persona, así que el mismo documento no se vuelve a fotografiar cuando el
    # cliente compra por segunda vez.
    #
    # max_width/max_height hacen que Odoo redimensione al guardar. Sin eso, cada foto de
    # un celular moderno entra al filestore con varios megas. 1600 px alcanza de sobra
    # para leer un documento.
    photo_dni_front = fields.Image(
        string="Foto del DNI - frente",
        max_width=1600,
        max_height=1600,
        help="Frente del documento del cliente. Opcional.",
    )
    photo_dni_back = fields.Image(
        string="Foto del DNI - dorso",
        max_width=1600,
        max_height=1600,
        help="Dorso del documento del cliente. Opcional.",
    )
    has_dni_photos = fields.Boolean(
        string="DNI completo",
        compute="_compute_has_dni_photos",
        store=True,
        help="Se enciende con las dos caras cargadas: un frente solo no alcanza para "
             "tener el documento del cliente.",
    )

    # E8: control de clientes problemáticos.
    problematic = fields.Boolean(
        string="Cliente problemático", default=False, tracking=True, copy=False,
    )
    problematic_reason = fields.Char(string="Motivo", copy=False)
    problematic_date = fields.Date(string="Marcado el", readonly=True, copy=False)
    problematic_user_id = fields.Many2one(
        "res.users", string="Marcado por", readonly=True, copy=False,
    )

    card_ids = fields.One2many(
        "cvi.card", "customer_id", string="Compras", readonly=True,
    )
    card_count = fields.Integer(string="Compras", compute="_compute_history")
    recovered_count = fields.Integer(
        string="Muebles retirados", compute="_compute_history",
    )
    overdue_card_count = fields.Integer(
        string="Tarjetas en mora", compute="_compute_history",
    )
    amount_residual = fields.Monetary(
        string="Saldo total", compute="_compute_history",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    suggest_problematic = fields.Boolean(
        string="Sugerido como problemático", compute="_compute_history",
        help="Se enciende solo cuando el cliente tuvo un mueble retirado o tiene "
             "tarjetas en mora. No marca nada: la decisión es del administrador "
             "(HU-27).",
    )

    _sql_constraints = [
        ("dni_unique_per_company", "UNIQUE(company_id, dni)",
         "Ya existe un cliente con ese DNI en esta empresa."),
    ]

    @api.model
    def _cvi_normalize_dni(self, dni):
        """Deja el DNI en su forma canónica: sin puntos, espacios ni guiones."""
        return DNI_CLEAN_RE.sub("", dni or "").upper()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("dni"):
                vals["dni"] = self._cvi_normalize_dni(vals["dni"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("dni"):
            vals["dni"] = self._cvi_normalize_dni(vals["dni"])
        return super().write(vals)

    @api.constrains("dni")
    def _check_dni(self):
        for customer in self:
            if not self._cvi_normalize_dni(customer.dni):
                raise ValidationError(_(
                    "El cliente %s necesita un DNI: es lo que lo identifica.",
                    customer.name,
                ))

    @api.depends("photo_dni_front", "photo_dni_back")
    def _compute_has_dni_photos(self):
        """El documento está completo recién con las dos caras cargadas."""
        for customer in self:
            customer.has_dni_photos = bool(
                customer.photo_dni_front and customer.photo_dni_back
            )

    @api.depends(
        "card_ids.state",
        "card_ids.overdue_installment_count",
        "card_ids.amount_residual",
    )
    def _compute_history(self):
        """Antecedentes del cliente (HU-27, HU-29)."""
        for customer in self:
            cards = customer.card_ids
            customer.card_count = len(cards)
            customer.recovered_count = len(
                cards.filtered(lambda c: c.state == "recovered")
            )
            customer.overdue_card_count = len(
                cards.filtered(lambda c: c.overdue_installment_count > 0)
            )
            customer.amount_residual = sum(cards.mapped("amount_residual"))
            customer.suggest_problematic = bool(
                customer.recovered_count or customer.overdue_card_count
            )

    @api.depends("name", "dni")
    def _compute_display_name(self):
        for customer in self:
            customer.display_name = "%s [%s]" % (customer.name, customer.dni)

    @api.model
    def _cvi_find_by_dni(self, dni):
        """Busca por DNI normalizado. Devuelve un recordset vacío si no existe.

        Es la única forma de buscar un cliente en el circuito de venta: buscar por
        nombre es lo que permitía que la misma persona entrara dos veces escrita
        distinto, que es justo lo que HU-28 quiere evitar.
        """
        normalized = self._cvi_normalize_dni(dni)
        if not normalized:
            return self.browse()
        return self.search([
            ("dni", "=", normalized),
            ("company_id", "=", self.env.company.id),
        ], limit=1)

    def _cvi_alerts(self):
        """Antecedentes a mostrarle al vendedor antes de venderle (HU-28).

        Con el DNI como identidad no hace falta cruzar homónimos: si es el mismo
        documento, es el mismo cliente y son sus propios antecedentes.
        """
        self.ensure_one()
        avisos = []
        if self.problematic:
            avisos.append(_(
                "Marcado como problemático el %(date)s por %(user)s: %(reason)s",
                date=self.problematic_date or _("sin fecha"),
                user=self.problematic_user_id.name or _("sin usuario"),
                reason=self.problematic_reason or _("sin motivo"),
            ))
        for card in self.card_ids.filtered(lambda c: c.state == "recovered"):
            avisos.append(_(
                "Se le retiró el mueble de %(card)s (vendedor %(vendor)s).",
                card=card.name, vendor=card.vendor_id.name,
            ))
        for card in self.card_ids.filtered(
            lambda c: c.overdue_installment_count > 0 and c.state != "recovered"
        ):
            avisos.append(_(
                "Tiene %(count)s cuotas vencidas en %(card)s (vendedor %(vendor)s).",
                count=card.overdue_installment_count,
                card=card.name,
                vendor=card.vendor_id.name,
            ))
        return avisos

    def action_open_problematic_wizard(self):
        """Abre el recuadro donde se escribe el motivo (HU-27).

        El botón no marca por sí solo: el motivo dejó de ser un campo suelto del
        formulario, así que pedirlo antes es lo que evita clientes señalados sin
        explicación.
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Marcar como mala paga"),
            "res_model": "cvi.problematic.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_customer_id": self.id},
        }

    def action_mark_problematic(self, reason=None):
        """Marca al cliente como mala paga, con motivo (HU-27).

        El motivo llega del recuadro. Sigue aceptando el que ya esté guardado en la
        ficha para no romper lo que llame a este método sin pasarlo.
        """
        self.ensure_one()
        motive = (reason or self.problematic_reason or "").strip()
        if not motive:
            raise UserError(_(
                "Cargá el motivo antes de marcar a %s como problemático.", self.name
            ))
        # _track_set_log_message le pone texto al mensaje que genera el tracking del
        # campo. Sin esto el historial mostraba solo "No -> Sí (Cliente problemático)",
        # que no dice por qué. Y va en el mismo mensaje, no en uno aparte, para no
        # dejar dos entradas por cada marca.
        self._track_set_log_message(_("Marcado como mala paga: %s", motive))
        self.write({
            "problematic": True,
            "problematic_reason": motive,
            "problematic_date": fields.Date.context_today(self),
            "problematic_user_id": self.env.user.id,
        })
        return True

    def action_unmark_problematic(self):
        """Levanta la marca, por ejemplo si el cliente regularizó."""
        self.ensure_one()
        self._track_set_log_message(_(
            "Marca de mala paga levantada. Motivo anterior: %s",
            self.problematic_reason or _("sin motivo"),
        ))
        self.write({
            "problematic": False,
            "problematic_date": False,
            "problematic_user_id": False,
        })
        return True
