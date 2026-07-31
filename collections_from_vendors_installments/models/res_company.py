# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    cvi_default_installments = fields.Integer(
        string="Cuotas por defecto",
        default=12,
        help="Cantidad de cuotas que se propone al cargar una venta nueva. El vendedor puede cambiarla.",
    )
    cvi_overdue_days = fields.Integer(
        string="Días de tolerancia de mora",
        default=0,
        help="Días de atraso que se toleran antes de marcar una cuota como vencida.",
    )
    cvi_allowed_frequencies = fields.Selection(
        selection=[
            ("both", "Mensual y semanal"),
            ("monthly", "Solo mensual"),
            ("weekly", "Solo semanal"),
        ],
        string="Frecuencias permitidas",
        default="both",
        required=True,
    )
