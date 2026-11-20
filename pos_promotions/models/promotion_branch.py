# -*- coding: utf-8 -*-

from odoo import api, fields, models


class PromotionBranch(models.Model):
    """Sucursal que se elige en una promoción: una por empresa, con su nombre copiado.

    El formulario muestra estas y no res.company porque la regla de empresas de Odoo no
    deja leer a un usuario las que no tiene activas en el selector, y la pantalla de
    Promociones fallaba con 'Error de acceso: Empresas'. Este modelo no tiene reglas: todos
    lo leen; qué sucursales se pueden elegir lo decide el dominio del campo.
    """

    _name = "pos.promotion.branch"
    _description = "Sucursal de promoción"
    _order = "name"

    company_id = fields.Many2one("res.company", required=True, ondelete="cascade", index=True)
    name = fields.Char(related="company_id.name", store=True, readonly=True)

    _sql_constraints = [
        ("company_unique", "unique(company_id)", "Cada empresa tiene una sola sucursal de promoción."),
    ]

    @api.model
    def _sync_branches(self):
        """Crea la sucursal de cada empresa que todavía no la tiene."""
        companies = self.env["res.company"].sudo().with_context(active_test=False).search([])
        existing = self.sudo().search([]).company_id
        missing = companies - existing
        if missing:
            self.sudo().create([{"company_id": company.id} for company in missing])

    @api.model
    def _for_companies(self, companies):
        """Sucursales de esas empresas (las crea si faltan)."""
        branches = self.sudo().search([("company_id", "in", companies.ids)])
        if len(branches) < len(companies):
            self._sync_branches()
            branches = self.sudo().search([("company_id", "in", companies.ids)])
        return branches


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        """Una empresa nueva ya aparece como sucursal en las promociones."""
        companies = super().create(vals_list)
        self.env["pos.promotion.branch"].sudo().create([{"company_id": company.id} for company in companies])
        return companies
