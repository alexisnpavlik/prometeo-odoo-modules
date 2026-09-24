from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_internal_company = fields.Boolean(
        string="Es empresa interna",
        compute="_compute_internal_company",
        help="El contacto es una empresa de este Odoo o una dirección hija de ella.",
    )
    internal_company_name = fields.Char(
        string="Empresa interna",
        compute="_compute_internal_company",
    )

    @api.depends("commercial_partner_id")
    def _compute_internal_company(self):
        """Marca el contacto si su entidad comercial es el contacto de alguna res.company."""
        companies = self.env["res.company"].sudo().with_context(active_test=False).search([])
        name_by_partner = {company.partner_id.id: company.name for company in companies}
        for partner in self:
            name = name_by_partner.get(partner.commercial_partner_id.id)
            partner.is_internal_company = bool(name)
            partner.internal_company_name = name or False
