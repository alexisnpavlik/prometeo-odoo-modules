# -*- coding: utf-8 -*-
from odoo import api, models


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config_id):
        """Agrega el maestro de motivos a los modelos cargados en el POS."""
        res = super()._load_pos_data_models(config_id)
        res.append("pos.deletion.reason")
        return res
