# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    is_pack_component = fields.Boolean(
        string="Componente de pack",
        default=False,
        help="La línea fue generada al explotar un pack 'detailed' en el POS. "
        "Permite al backend saber qué componentes ya están cubiertos por una "
        "línea propia y cuáles hay que descontar desde el pack.",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Sincroniza la marca de componente entre el POS y el backend."""
        fields_list = super()._load_pos_data_fields(config_id)
        fields_list.append("is_pack_component")
        return fields_list
