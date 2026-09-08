# -*- coding: utf-8 -*-
from odoo import fields, models

ABC_SELECTION = [("a", "A"), ("b", "B"), ("c", "C")]
XYZ_SELECTION = [("x", "X"), ("y", "Y"), ("z", "Z")]


class ProductCategory(models.Model):
    _inherit = "product.category"

    demand_model_id = fields.Many2one(
        "prometeo.demand.model", string="Modelo de demanda",
        help="Modelo usado para los productos de esta categoría, salvo que el "
             "producto tenga uno propio.",
    )


class ProductTemplate(models.Model):
    _inherit = "product.template"

    demand_model_id = fields.Many2one(
        "prometeo.demand.model", string="Modelo de demanda",
        help="Fuerza un modelo de estimación para este producto, por encima de "
             "la categoría y de las reglas.",
    )
    exclude_from_suggestion = fields.Boolean(
        string="Excluir del recomendador",
        help="El producto no aparece en las sugerencias de compra.",
    )


class ProductProduct(models.Model):
    _inherit = "product.product"

    # Escritas por el cron semanal de clasificación, no en cada sugerencia:
    # recalcularlas por corrida sería caro y las clases no cambian a diario.
    abc_class = fields.Selection(
        ABC_SELECTION, string="Clase ABC", readonly=True, index=True,
        help="Contribución al margen de los últimos 180 días. "
             "A: primeros 80%. B: hasta 95%. C: el resto.",
    )
    xyz_class = fields.Selection(
        XYZ_SELECTION, string="Clase XYZ", readonly=True, index=True,
        help="Variabilidad de la demanda. X: estable. Y: variable. Z: errática.",
    )
    abc_xyz_date = fields.Datetime(
        string="Clasificado el", readonly=True,
        help="Última vez que el cron recalculó las clases ABC/XYZ.",
    )
