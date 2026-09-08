# -*- coding: utf-8 -*-
from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    auto_suggestion = fields.Boolean(
        string="Sugerencia automática",
        help="Genera una sugerencia de compra calculada todas las semanas y le "
             "asigna una actividad al responsable.",
    )
    suggestion_user_id = fields.Many2one(
        "res.users", string="Responsable de compras",
        help="Recibe la actividad cuando se genera la sugerencia semanal.",
    )
