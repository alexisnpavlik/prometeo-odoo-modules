from odoo import _, models
from odoo.exceptions import UserError

# Campos de pos.config que apuntan a productos de sistema. Cada uno viene de un
# módulo opcional (pos_discount, pos_global_surcharge_button): se usan sólo los
# que existen en el registry, así el bloqueo funciona con cualquiera instalado.
PROTECTED_POS_CONFIG_FIELDS = ("discount_product_id", "surcharge_product_id")


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _get_protected_product_ids(self):
        """Devuelve los ids de las variantes usadas como descuento o recargo en alguna caja.

        Sin punto de venta instalado, o sin ninguno de los dos campos, no protege nada.
        """
        if "pos.config" not in self.env:
            return set()
        pos_config = self.env["pos.config"]
        fields_present = [f for f in PROTECTED_POS_CONFIG_FIELDS if f in pos_config._fields]
        if not fields_present:
            return set()
        configs = pos_config.sudo().with_context(active_test=False).search([])
        protected_ids = set()
        for field_name in fields_present:
            protected_ids.update(configs.mapped(field_name).ids)
        return protected_ids

    def _check_protected_product_edit(self):
        """Bloquea la operación si toca un producto de sistema y el usuario no es administrador."""
        if self.env.su or self.env.user.has_group("base.group_system"):
            return
        protected = self.filtered(lambda p: p.id in self._get_protected_product_ids())
        if protected:
            raise UserError(_(
                "No podés modificar el producto %s: está protegido porque el punto de venta lo usa para descuentos o recargos. Pedíselo a un administrador.",
                ", ".join(protected.mapped("display_name")),
            ))

    def write(self, vals):
        """Impide editar o archivar variantes protegidas."""
        self._check_protected_product_edit()
        return super().write(vals)

    def unlink(self):
        """Impide borrar variantes protegidas."""
        self._check_protected_product_edit()
        return super().unlink()
