# -*- coding: utf-8 -*-
from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    cvi_is_vendor_location = fields.Boolean(
        string="Es ubicación de un vendedor",
        default=False,
        index=True,
        copy=False,
        help="Marca las ubicaciones que representan la mercadería que un vendedor "
             "tiene en la calle. Es lo que filtra el reporte de mercadería en la calle.",
    )

    cvi_is_recovered_location = fields.Boolean(
        string="Es la ubicación de muebles retirados",
        default=False,
        index=True,
        copy=False,
        help="Marca la ubicación donde entran los muebles retirados a clientes que "
             "dejaron de pagar. Es lo que filtra el reporte de muebles retirados.",
    )
