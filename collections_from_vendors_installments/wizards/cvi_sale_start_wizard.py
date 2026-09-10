# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class CviSaleStartWizard(models.TransientModel):
    _name = "cvi.sale.start.wizard"
    _description = "Inicio de venta: identificar al cliente por DNI"

    dni = fields.Char(string="DNI del cliente", required=True)
    customer_id = fields.Many2one(
        "cvi.customer", string="Cliente encontrado", readonly=True,
    )
    found = fields.Boolean(string="Ya existe", readonly=True)
    searched = fields.Boolean(string="Búsqueda hecha", readonly=True)
    alert = fields.Text(string="Antecedentes", readonly=True)
    has_alert = fields.Boolean(string="Tiene antecedentes", readonly=True)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
        readonly=True,
    )
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

    # Datos para dar de alta al cliente cuando el DNI no existe.
    name = fields.Char(string="Nombre y apellido")
    mobile = fields.Char(string="Celular")
    street = fields.Char(string="Dirección")
    city_id = fields.Many2one("cvi.city", string="Ciudad")
    zip = fields.Char(string="Código postal")
    photo_dni_front = fields.Image(
        string="Foto del DNI - frente",
        max_width=1600,
        max_height=1600,
    )
    photo_dni_back = fields.Image(
        string="Foto del DNI - dorso",
        max_width=1600,
        max_height=1600,
    )

    def action_search(self):
        """Busca por DNI y muestra el resultado sin salir del asistente (HU-28).

        La búsqueda es por documento y nunca por nombre: buscar por nombre es lo que
        permitía que la misma persona entrara dos veces escrita distinto.
        """
        self.ensure_one()
        customer = self.env["cvi.customer"]._cvi_find_by_dni(self.dni)
        alerts = customer._cvi_alerts() if customer else []
        self.write({
            "searched": True,
            "customer_id": customer.id,
            "found": bool(customer),
            "alert": "\n".join(alerts) or False,
            "has_alert": bool(alerts),
            "name": customer.name if customer else self.name,
            "mobile": customer.mobile if customer else self.mobile,
            "street": customer.street if customer else self.street,
            "city_id": customer.city_id.id if customer else self.city_id.id,
            "zip": customer.zip if customer else self.zip,
            "photo_dni_front": (
                customer.photo_dni_front if customer else self.photo_dni_front
            ),
            "photo_dni_back": (
                customer.photo_dni_back if customer else self.photo_dni_back
            ),
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
        }

    def action_start_sale(self):
        """Crea el cliente si hace falta y abre la venta con él ya puesto."""
        self.ensure_one()
        if not self.searched:
            raise UserError(_("Buscá el DNI antes de continuar."))
        customer = self.customer_id
        if not customer:
            if not self.name:
                raise UserError(_(
                    "Cargá el nombre para dar de alta al cliente con DNI %s.", self.dni
                ))
            customer = self.env["cvi.customer"].create({
                "dni": self.dni,
                "name": self.name,
                "mobile": self.mobile,
                "street": self.street,
                "city_id": self.city_id.id,
                "zip": self.zip,
                "photo_dni_front": self.photo_dni_front,
                "photo_dni_back": self.photo_dni_back,
            })
        # La tarjeta no se crea acá: se abre el formulario con el cliente puesto y se
        # graba cuando tenga mercadería. Una venta sin muebles tiene total cero y el
        # constraint amount_total > 0 la rechaza, que es justamente lo que queremos.
        return {
            "type": "ir.actions.act_window",
            "name": _("Venta"),
            "res_model": "cvi.card",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
            "context": {
                "default_customer_id": customer.id,
                "default_vendor_id": self.env.user.id,
            },
        }
