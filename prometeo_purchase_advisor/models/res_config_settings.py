# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    # No se llama default_* a propósito: res.config.settings reserva ese
    # prefijo para los campos que fijan valores por defecto de otro modelo, y
    # explota al abrir la pantalla de ajustes.
    suggestion_demand_model_id = fields.Many2one(
        "prometeo.demand.model", string="Modelo de demanda por defecto",
        help="Modelo usado cuando el producto, su categoría y las reglas no "
             "resuelven ninguno.",
    )
    suggestion_coverage_days = fields.Integer(
        string="Días de cobertura objetivo", default=30,
        help="Cuántos días de venta se quiere tener cubiertos además del lead time.",
    )
    suggestion_always_include_c = fields.Boolean(
        string="Incluir siempre los productos C",
        help="Sin esto, los productos de clase C solo aparecen cuando van a "
             "quebrar antes de que llegue la reposición. Activarlo llena la "
             "sugerencia con la cola larga del surtido.",
    )

    @api.model
    def _prometeo_default_demand_model(self):
        """Modelo de demanda por defecto de la compañía activa.

        Si la compañía no tiene uno configurado cae al modelo de datos del
        módulo, para que el recomendador nunca quede sin método utilizable.
        """
        model = self.env.company.suggestion_demand_model_id
        if model:
            return model
        return self.env.ref(
            "prometeo_purchase_advisor.demand_model_default",
            raise_if_not_found=False,
        ) or self.env["prometeo.demand.model"]


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    suggestion_demand_model_id = fields.Many2one(
        related="company_id.suggestion_demand_model_id", readonly=False,
        string="Modelo de demanda por defecto",
    )
    suggestion_coverage_days = fields.Integer(
        related="company_id.suggestion_coverage_days", readonly=False,
        string="Días de cobertura objetivo",
    )
    suggestion_always_include_c = fields.Boolean(
        related="company_id.suggestion_always_include_c", readonly=False,
        string="Incluir siempre los productos C",
    )
