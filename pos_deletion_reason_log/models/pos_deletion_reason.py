# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosDeletionReason(models.Model):
    _name = "pos.deletion.reason"
    _description = "Motivo de eliminación en POS"
    _inherit = ["pos.load.mixin"]
    _order = "sequence, id"

    name = fields.Char(string="Motivo", required=True, translate=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activo", default=True)

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Campos del motivo que se cargan al frontend del POS."""
        return ["id", "name"]
