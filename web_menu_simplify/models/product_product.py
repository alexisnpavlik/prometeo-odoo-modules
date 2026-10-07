# -*- coding: utf-8 -*-

from odoo import api, models

from .simplify_options import active_button_options, hide_option_buttons


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        """Oculta los botones de las opciones activadas en Ajustes (incluye Existencias)."""
        arch, view = super()._get_view(view_id, view_type, **options)
        hide_option_buttons(self.env, arch, view_type)
        return arch, view

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type="form", **options):
        """Separa la caché de vistas según qué opciones de botones están activadas."""
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + active_button_options(self.env)
