from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _default_country_ar(self):
        """País por defecto de los contactos nuevos: Argentina."""
        return self.env.ref("base.ar", raise_if_not_found=False)

    def _default_identification_type_dni(self):
        """Tipo de documento por defecto: CUIT para empresas, DNI para personas."""
        if self.env.context.get("default_is_company") or self.env.context.get("default_company_type") == "company":
            return self.env.ref("l10n_ar.it_cuit", raise_if_not_found=False)
        return self.env.ref("l10n_ar.it_dni", raise_if_not_found=False)

    country_id = fields.Many2one(default=_default_country_ar)
    l10n_latam_identification_type_id = fields.Many2one(default=_default_identification_type_dni)

    @api.onchange("is_company")
    def _onchange_is_company_identification_type(self):
        """En contactos nuevos alterna DNI y CUIT según sea persona o empresa; no toca CUIL ni otros tipos."""
        dni = self.env.ref("l10n_ar.it_dni", raise_if_not_found=False)
        cuit = self.env.ref("l10n_ar.it_cuit", raise_if_not_found=False)
        for partner in self.filtered(lambda p: not p._origin.id):
            if partner.is_company and partner.l10n_latam_identification_type_id == dni:
                partner.l10n_latam_identification_type_id = cuit
            elif not partner.is_company and partner.l10n_latam_identification_type_id == cuit:
                partner.l10n_latam_identification_type_id = dni
