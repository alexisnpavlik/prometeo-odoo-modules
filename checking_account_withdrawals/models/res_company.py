# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    caw_installment_count = fields.Integer(
        string="Cuotas por defecto",
        default=1,
        help="Cantidad de cuotas propuesta al confirmar un retiro.",
    )
    caw_installment_days = fields.Integer(
        string="Días hasta el primer vencimiento",
        default=30,
        help="Días desde la fecha del retiro hasta el vencimiento de la primera cuota.",
    )
    caw_installment_period = fields.Selection(
        selection=[("days", "Días"), ("weeks", "Semanas"), ("months", "Meses")],
        string="Periodicidad de cuotas",
        default="months",
    )
    caw_cutoff_day = fields.Integer(
        string="Día de corte",
        default=0,
        help="Día del mes al que se ajustan los vencimientos. 0 = sin día de corte.",
    )
    caw_picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Tipo de operación para retiros",
        domain="[('code', '=', 'outgoing'), ('company_id', '=', id)]",
        help="Tipo de operación usado para el albarán de salida del retiro. "
             "Si está vacío se usa el de salidas del almacén principal.",
    )
