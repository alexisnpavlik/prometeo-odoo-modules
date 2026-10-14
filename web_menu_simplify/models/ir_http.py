# -*- coding: utf-8 -*-

from odoo import models

from .simplify_options import is_option_active


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        """Le indica al cliente web las opciones que resuelve el frontend."""
        result = super().session_info()
        result["web_menu_simplify_hide_systray"] = is_option_active(self.env, "hide_systray")
        return result
