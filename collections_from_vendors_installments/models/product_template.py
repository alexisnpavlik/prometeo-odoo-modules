# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    cvi_plan_ids = fields.One2many(
        "cvi.product.plan",
        "product_tmpl_id",
        string="Planes de cuotas",
        help="Cómo se vende este mueble en la calle: un plan por cada combinación "
             "de cantidad de cuotas e importe.",
    )
    cvi_plan_count = fields.Integer(
        string="Planes de cuotas", compute="_compute_cvi_plan_count"
    )

    @api.depends("cvi_plan_ids")
    def _compute_cvi_plan_count(self):
        """Cuántos planes activos tiene el mueble, para el botón de la ficha."""
        for template in self:
            template.cvi_plan_count = len(template.cvi_plan_ids)
