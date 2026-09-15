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
    cvi_settlement_frequency = fields.Selection(
        selection=[
            ("daily", "Diaria"),
            ("weekly", "Semanal"),
            ("monthly", "Mensual"),
        ],
        string="Frecuencia de rendición",
        default="daily",
        required=True,
        help="Cada cuánto los cobradores rinden la caja (HU-18).",
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
    cvi_customer_mobile_required = fields.Boolean(
        string="Exigir celular del cliente",
        default=True,
    )
    cvi_customer_street_required = fields.Boolean(
        string="Exigir dirección del cliente",
        default=True,
    )
    cvi_customer_city_required = fields.Boolean(
        string="Exigir ciudad del cliente",
        default=True,
    )
    cvi_customer_zip_required = fields.Boolean(
        string="Exigir código postal del cliente",
        default=True,
    )
    cvi_customer_dni_photos_required = fields.Boolean(
        string="Exigir fotos del DNI",
        default=False,
    )
