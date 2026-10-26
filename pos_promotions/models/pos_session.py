# -*- coding: utf-8 -*-

from odoo import api, models


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config_id):
        """Carga los componentes de los packs para detectarlos en la orden."""
        return super()._load_pos_data_models(config_id) + ["pos.promotion.pack.line"]
