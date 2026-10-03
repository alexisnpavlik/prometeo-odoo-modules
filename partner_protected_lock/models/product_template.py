from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _check_protected_product_edit(self):
        """Bloquea si alguna variante de la plantilla es un producto de sistema del POS.

        Nombre, impuestos y precio se editan en la plantilla: no alcanza con proteger product.product.
        """
        self.with_context(active_test=False).product_variant_ids._check_protected_product_edit()

    def write(self, vals):
        """Impide editar o archivar plantillas de productos protegidos."""
        self._check_protected_product_edit()
        return super().write(vals)

    def unlink(self):
        """Impide borrar plantillas de productos protegidos."""
        self._check_protected_product_edit()
        return super().unlink()
