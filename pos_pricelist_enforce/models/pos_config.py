# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    pricelist_enforce = fields.Boolean(
        string="Forzar precio de lista al cobrar",
        default=False,
        help="Antes de cobrar, re-aplica el precio de la lista a las líneas que "
             "quedaron a precio público, corrigiendo el bug intermitente del POS. "
             "Solo actúa sobre reglas de precio fijo con valor mayor a 0.",
    )
    pricelist_enforce_warn = fields.Boolean(
        string="Avisar al corregir",
        default=True,
        help="Muestra una notificación al cajero cuando se corrige alguna línea "
             "al ir a cobrar.",
    )
