# -*- coding: utf-8 -*-

from odoo import Command, api, fields, models

from .product_template import ALLOWED_COMPANIES_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    promotion_allowed_company_ids = fields.Many2many(
        "res.company",
        "pos_promotions_settings_company_rel",
        "settings_id",
        "company_id",
        string="Sucursales permitidas en promociones",
    )

    @api.model
    def get_values(self):
        """Lee las sucursales permitidas del parámetro del sistema (ids separados por coma)."""
        res = super().get_values()
        raw = self.env["ir.config_parameter"].sudo().get_param(ALLOWED_COMPANIES_PARAM, "")
        ids = [int(value) for value in raw.split(",") if value.strip().isdigit()]
        existing = self.env["res.company"].sudo().browse(ids).exists() & self.env.user.company_ids
        res["promotion_allowed_company_ids"] = [Command.set(existing.ids)]
        return res

    def set_values(self):
        """Guarda las sucursales permitidas; vacío significa todas. Conserva las que el
        usuario no ve (empresas a las que no tiene acceso)."""
        super().set_values()
        param = self.env["ir.config_parameter"].sudo()
        raw = param.get_param(ALLOWED_COMPANIES_PARAM, "")
        hidden = [int(v) for v in raw.split(",") if v.strip().isdigit() and int(v) not in self.env.user.company_ids.ids]
        param.set_param(ALLOWED_COMPANIES_PARAM, ",".join(str(cid) for cid in hidden + self.promotion_allowed_company_ids.ids))
