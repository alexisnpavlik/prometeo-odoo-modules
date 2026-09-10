from odoo import api, fields, models


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

    # Visibilidad de las pestañas del formulario. Cada una depende de su grupo,
    # que se maneja como casilla desde Ajustes > Inventario.
    can_edit_product_defaults = fields.Boolean(
        string="Puede editar valores por defecto de producto",
        compute="_compute_product_form_flags",
    )
    show_page_variants = fields.Boolean(
        string="Ver pestaña Atributos y variantes",
        compute="_compute_product_form_flags",
    )
    show_page_sales = fields.Boolean(
        string="Ver pestaña Ventas",
        compute="_compute_product_form_flags",
    )
    show_page_purchase = fields.Boolean(
        string="Ver pestaña Compras",
        compute="_compute_product_form_flags",
    )
    show_page_inventory = fields.Boolean(
        string="Ver pestaña Inventario",
        compute="_compute_product_form_flags",
    )
    show_page_pos = fields.Boolean(
        string="Ver pestaña Punto de venta",
        compute="_compute_product_form_flags",
    )

    @api.depends_context("uid")
    def _compute_product_form_flags(self):
        """Resuelve de una sola vez los grupos que gobiernan la ficha de producto.

        depends_context("uid") es obligatorio: sin eso el caché de un usuario se
        reutilizaría para otro y las pestañas se verían mal.
        """
        user = self.env.user
        flags = {
            "can_edit_product_defaults": user.has_group(
                "product_default_settings.group_edit_product_defaults"
            ),
            "show_page_variants": user.has_group(
                "product_default_settings.group_show_page_variants"
            ),
            "show_page_sales": user.has_group(
                "product_default_settings.group_show_page_sales"
            ),
            "show_page_purchase": user.has_group(
                "product_default_settings.group_show_page_purchase"
            ),
            "show_page_inventory": user.has_group(
                "product_default_settings.group_show_page_inventory"
            ),
            "show_page_pos": user.has_group(
                "product_default_settings.group_show_page_pos"
            ),
        }
        for record in self:
            record.update(flags)
