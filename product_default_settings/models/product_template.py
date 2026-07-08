from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Valores por defecto fijos. El bloqueo (readonly/gris) se aplica en la vista
    # y depende del grupo "Editar valores por defecto de producto".
    type = fields.Selection(default="consu")            # Tipo de producto: Bien
    is_storable = fields.Boolean(default=True)          # Rastrear inventario
    invoice_policy = fields.Selection(default="order")  # Política de facturación: Cantidades pedidas
    sale_ok = fields.Boolean(default=True)              # Ventas
    purchase_ok = fields.Boolean(default=True)          # Compras
    available_in_pos = fields.Boolean(default=True)     # Punto de venta

    can_edit_product_defaults = fields.Boolean(
        string="Puede editar valores por defecto de producto",
        compute="_compute_can_edit_product_defaults",
    )

    def _compute_can_edit_product_defaults(self):
        """True si el usuario pertenece al grupo que habilita editar los campos bloqueados."""
        can_edit = self.env.user.has_group(
            "product_default_settings.group_edit_product_defaults"
        )
        for record in self:
            record.can_edit_product_defaults = can_edit
