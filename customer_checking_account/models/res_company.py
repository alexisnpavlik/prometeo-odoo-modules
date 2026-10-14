# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    cca_default_credit_limit = fields.Monetary(
        string="Límite de crédito por defecto",
        currency_field="currency_id",
        help="Límite que toma cada cuenta nueva. 0 = sin límite.",
    )
    cca_default_limit_mode = fields.Selection(
        selection=[("none", "Sin control"), ("warn", "Advertencia"), ("block", "Bloqueo")],
        string="Modo de límite por defecto",
        default="none",
    )
    cca_picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Tipo de operación para retiros",
        domain="[('code', '=', 'outgoing'), ('company_id', '=', id)]",
        help="Vacío = salidas del almacén principal de la compañía.",
    )

    cca_late_fee_enabled = fields.Boolean(
        string="Cobrar mora por atraso",
        help="Suma un monto fijo por cada día que una cuota sigue impaga después de los días de gracia.",
    )
    cca_late_fee_grace_days = fields.Integer(
        string="Días de gracia",
        default=0,
        help="Días después del vencimiento en los que todavía no corre la mora.",
    )
    cca_late_fee_daily_amount = fields.Monetary(
        string="Mora por día",
        currency_field="currency_id",
        help="Monto que se suma por cada día de atraso, por cuota.",
    )
