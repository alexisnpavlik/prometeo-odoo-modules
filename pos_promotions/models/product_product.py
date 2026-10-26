# -*- coding: utf-8 -*-

from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config_id):
        """El POS necesita saber qué productos son packs para mostrarlos sin categoría."""
        return super()._load_pos_data_fields(config_id) + ["is_promotion_pack"]
