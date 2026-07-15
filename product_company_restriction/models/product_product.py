import logging

from odoo import _, api, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

GROUP = "product_company_restriction.group_product_company_restricted"


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _is_company_restricted_user(self):
        """Ver product_template._is_company_restricted_user."""
        return not self.env.su and self.env.user.has_group(GROUP)

    def _check_company_restriction(self):
        """Bloquea tocar variantes que no sean de una compañía permitida."""
        if not self._is_company_restricted_user():
            return
        allowed = set(self.env.user.company_ids.ids)
        for rec in self:
            if not rec.company_id or rec.company_id.id not in allowed:
                raise AccessError(
                    _("Solo puede crear o modificar productos de su propia empresa.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Fuerza company_id a la empresa activa del usuario restringido."""
        if self._is_company_restricted_user():
            allowed = set(self.env.user.company_ids.ids)
            company_id = self.env.company.id
            for vals in vals_list:
                if not vals.get("company_id"):
                    vals["company_id"] = company_id
                elif vals["company_id"] not in allowed:
                    raise AccessError(
                        _("Solo puede crear productos de su propia empresa.")
                    )
        return super().create(vals_list)

    def write(self, vals):
        self._check_company_restriction()
        if self._is_company_restricted_user() and "company_id" in vals:
            allowed = set(self.env.user.company_ids.ids)
            if vals["company_id"] not in allowed:
                raise AccessError(_("No puede mover el producto a otra empresa."))
        return super().write(vals)

    def unlink(self):
        self._check_company_restriction()
        return super().unlink()
