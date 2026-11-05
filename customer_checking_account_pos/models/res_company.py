# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    cca_pos_surcharge_percent = fields.Float(
        string="Recargo por financiación (%)",
        digits=(5, 2),
        default=0.0,
        help="Recargo que se aplica a las ventas a cuenta corriente desde el POS.",
    )
    cca_pos_installment_count = fields.Integer(
        string="Cantidad de cuotas",
        default=1,
        help="Cuotas por defecto de las ventas a cuenta corriente desde el POS.",
    )
    cca_pos_first_due_days = fields.Integer(
        string="Días a la primera cuota",
        default=30,
        help="Días desde la venta hasta el vencimiento de la primera cuota.",
    )
    cca_pos_frequency = fields.Selection(
        selection=[("monthly", "Mensual"), ("weekly", "Semanal")],
        string="Frecuencia de cuotas",
        default="monthly",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Agrega al POS los valores de financiación de cuenta corriente."""
        fields_list = super()._load_pos_data_fields(config_id)
        return fields_list + [
            "cca_pos_surcharge_percent",
            "cca_pos_installment_count",
            "cca_pos_first_due_days",
            "cca_pos_frequency",
        ]
