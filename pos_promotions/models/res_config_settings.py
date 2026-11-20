# -*- coding: utf-8 -*-

from odoo import Command, api, fields, models

from .product_template import ALLOWED_PRICELISTS_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    promotion_allowed_pricelist_ids = fields.Many2many(
        "product.pricelist",
        "pos_promotions_settings_pricelist_rel",
        "settings_id",
        "pricelist_id",
        string="Listas permitidas en promociones",
    )

    @api.model
    def get_values(self):
        """Lee las listas permitidas del parámetro del sistema (ids separados por coma)."""
        res = super().get_values()
        raw = self.env["ir.config_parameter"].sudo().get_param(ALLOWED_PRICELISTS_PARAM, "")
        ids = [int(value) for value in raw.split(",") if value.strip().isdigit()]
        existing = self.env["product.pricelist"].sudo().browse(ids).exists()
        res["promotion_allowed_pricelist_ids"] = [Command.set(existing.ids)]
        return res

    def set_values(self):
        """Guarda las listas permitidas; vacío significa todas."""
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            ALLOWED_PRICELISTS_PARAM, ",".join(str(pid) for pid in self.promotion_allowed_pricelist_ids.ids)
        )
