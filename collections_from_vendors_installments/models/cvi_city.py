# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CviCity(models.Model):
    _name = "cvi.city"
    _description = "Ciudad donde se vende y se cobra"
    _order = "state_id, name"

    name = fields.Char(string="Ciudad", required=True)
    state_id = fields.Many2one(
        "res.country.state",
        string="Provincia",
        index=True,
        help="Provincia a la que pertenece la ciudad. Las carga Odoo, no este módulo.",
    )
    active = fields.Boolean(
        string="Activa",
        default=True,
        help="Una ciudad archivada deja de ofrecerse en las fichas nuevas, "
             "pero los clientes que ya la tienen no se tocan.",
    )

    _sql_constraints = [
        ("name_unique_per_state", "UNIQUE(name, state_id)",
         "Esa ciudad ya está cargada en esa provincia."),
    ]

    @api.depends("name", "state_id")
    def _compute_display_name(self):
        """Se muestra con la provincia: hay homónimas en distintas provincias."""
        for city in self:
            if city.state_id:
                city.display_name = "%s (%s)" % (city.name, city.state_id.name)
            else:
                city.display_name = city.name or ""
