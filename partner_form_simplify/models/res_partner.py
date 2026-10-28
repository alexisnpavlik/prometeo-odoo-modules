from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _default_country_ar(self):
        """País por defecto de los contactos nuevos: Argentina."""
        return self.env.ref("base.ar", raise_if_not_found=False)

    def _default_identification_type_dni(self):
        """Tipo de documento por defecto: DNI."""
        return self.env.ref("l10n_ar.it_dni", raise_if_not_found=False)

    country_id = fields.Many2one(default=_default_country_ar)
    l10n_latam_identification_type_id = fields.Many2one(default=_default_identification_type_dni)
