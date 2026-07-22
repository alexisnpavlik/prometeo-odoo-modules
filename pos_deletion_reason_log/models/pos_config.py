# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

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

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Asegura que los toggles de motivo lleguen al frontend del POS."""
        fields_list = super()._load_pos_data_fields(config_id)
        fields_list += [
            "require_reason_order_deletion",
            "require_reason_line_deletion",
            "require_reason_qty_reduction",
        ]
        return fields_list
