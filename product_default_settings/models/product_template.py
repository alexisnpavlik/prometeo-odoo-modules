from odoo import fields, models

from .res_config_settings import get_product_form_settings


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Valores por defecto fijos. El bloqueo (readonly/gris) se aplica en la vista
    # y depende del ajuste global "Permitir editar los valores por defecto".
    type = fields.Selection(default="consu")            # Tipo de producto: Bien
    is_storable = fields.Boolean(default=True)          # Rastrear inventario
    invoice_policy = fields.Selection(default="order")  # Política de facturación: Cantidades pedidas
    sale_ok = fields.Boolean(default=True)              # Ventas
    purchase_ok = fields.Boolean(default=True)          # Compras
    available_in_pos = fields.Boolean(default=True)     # Punto de venta

    # Visibilidad de las pestañas del formulario. Cada una depende de un ajuste
    # global de Ajustes > Formulario de producto (igual para todos los usuarios).
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

    def _compute_product_form_flags(self):
        """Resuelve de una sola vez los ajustes globales que gobiernan la ficha.

        Vienen de Ajustes > Formulario de producto (ir.config_parameter) y valen
        igual para todos los usuarios.
        """
        settings = get_product_form_settings(self.env)
        flags = {
            "can_edit_product_defaults": settings["edit_defaults"],
            "show_page_variants": settings["show_page_variants"],
            "show_page_sales": settings["show_page_sales"],
            "show_page_purchase": settings["show_page_purchase"],
            "show_page_inventory": settings["show_page_inventory"],
            "show_page_pos": settings["show_page_pos"],
        }
        for record in self:
            record.update(flags)
