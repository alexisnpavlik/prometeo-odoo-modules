# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    # NO sobrescribir _load_pos_data_fields en pos.config: el mixin devuelve []
    # a propósito, y una lista vacía hace que search_read cargue TODOS los campos
    # (incluido use_pricelist, que el core lee sin chequeo en _load_pos_data).
    # Devolver una lista acotada rompe el POS con KeyError: 'use_pricelist'.
    # Estos toggles llegan solos al frontend por la carga completa de pos.config.
    require_reason_order_deletion = fields.Boolean(
        string="Motivo al eliminar orden",
        help="Pide un motivo cuando el cajero elimina una orden completa.",
    )
    require_reason_line_deletion = fields.Boolean(
        string="Motivo al eliminar línea",
        help="Pide un motivo cuando el cajero borra una línea/producto de la orden.",
    )
    require_reason_qty_reduction = fields.Boolean(
        string="Motivo al reducir cantidad",
        help="Pide un motivo cuando el cajero reduce la cantidad de una línea.",
    )
