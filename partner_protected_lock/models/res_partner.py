from odoo import _, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _get_protected_partner_ids(self):
        """Devuelve los ids protegidos: Consumidor Final Anónimo + contacto de cada empresa."""
        companies = self.env["res.company"].sudo().with_context(active_test=False).search([])
        protected_ids = set(companies.partner_id.ids)
        cfa = self.env.ref("l10n_ar.par_cfa", raise_if_not_found=False)
        if cfa:
            protected_ids.add(cfa.id)
        return protected_ids

    def _check_protected_partner_edit(self):
        """Bloquea la operación si toca un contacto protegido y el usuario no es administrador."""
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        protected = self.filtered(lambda p: p.id in self._get_protected_partner_ids())
        if protected:
            raise UserError(_(
                "No podés modificar el contacto %s: está protegido. Pedíselo a un administrador.",
                ", ".join(protected.mapped("display_name")),
            ))

    def write(self, vals):
        """Impide editar o archivar contactos protegidos."""
        self._check_protected_partner_edit()
        return super().write(vals)

    def unlink(self):
        """Impide borrar contactos protegidos."""
        self._check_protected_partner_edit()
        return super().unlink()
