import logging

from odoo import _, api, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

GROUP = "product_company_restriction.group_product_company_restricted"


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _is_company_restricted_user(self):
        """True si el usuario actual está restringido a productos de su empresa.

        No aplica al superusuario/sudo. La comprobación es por GRUPO (el check),
        no por reglas de registro, para ser inmune a la combinación OR de
        ir.rule (bypass de dominio-verdadero de otros módulos)."""
        return (
            not self.env.su
            and self.env.user.has_group(GROUP)
        )

    def _check_company_restriction(self):
        """Bloquea tocar productos que no sean de una compañía permitida del
        usuario. Los productos globales (company_id vacío) y los de otras
        empresas quedan vedados para el usuario restringido."""
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
        """Fuerza company_id a la empresa activa del usuario restringido; si se
        intenta crear para otra compañía, se rechaza."""
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
        """Impide que el usuario restringido edite productos ajenos o mueva un
        producto propio a otra compañía."""
        self._check_company_restriction()
        if self._is_company_restricted_user() and "company_id" in vals:
            allowed = set(self.env.user.company_ids.ids)
            if vals["company_id"] not in allowed:
                raise AccessError(
                    _("No puede mover el producto a otra empresa.")
                )
        return super().write(vals)

    def unlink(self):
        """Impide que el usuario restringido elimine productos ajenos."""
        self._check_company_restriction()
        return super().unlink()
