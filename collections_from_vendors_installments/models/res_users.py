# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    cvi_stock_location_id = fields.Many2one(
        "stock.location",
        string="Ubicación de mercadería",
        readonly=True,
        copy=False,
        help="Ubicación interna donde vive la mercadería que este vendedor tiene en la calle. "
             "Se crea sola la primera vez que se le entrega mercadería.",
    )

    def _cvi_get_location(self):
        """Devuelve la ubicación de stock del vendedor, creándola si todavía no existe.

        Se crea on-demand para no obligar a configurar una ubicación por usuario antes
        de empezar a operar.
        """
        self.ensure_one()
        if self.cvi_stock_location_id:
            return self.cvi_stock_location_id
        parent = self.env.ref("collections_from_vendors_installments.stock_location_vendors")
        location = self.env["stock.location"].sudo().create({
            "name": self.name,
            "usage": "internal",
            "location_id": parent.id,
            "company_id": self.company_id.id,
            "cvi_is_vendor_location": True,
        })
        self.sudo().cvi_stock_location_id = location
        return location
