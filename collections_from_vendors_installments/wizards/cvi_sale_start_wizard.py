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

    # Datos para dar de alta al cliente cuando el DNI no existe.
    name = fields.Char(string="Nombre y apellido")
    phone = fields.Char(string="Teléfono")
    mobile = fields.Char(string="Celular")
    street = fields.Char(string="Dirección")
    city = fields.Char(string="Ciudad")

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
            "phone": customer.phone if customer else self.phone,
            "mobile": customer.mobile if customer else self.mobile,
            "street": customer.street if customer else self.street,
            "city": customer.city if customer else self.city,
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
                "phone": self.phone,
                "mobile": self.mobile,
                "street": self.street,
                "city": self.city,
            })
        card = self.env["cvi.card"].create({
            "customer_id": customer.id,
            "vendor_id": self.env.user.id,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Venta"),
            "res_model": "cvi.card",
            "res_id": card.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
        }
