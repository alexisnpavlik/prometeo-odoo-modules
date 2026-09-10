from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Casillas de Ajustes > Inventario > Formulario de producto. `implied_group`
    # es el mecanismo nativo: tildar da el grupo a todos los usuarios internos,
    # destildar se lo quita. Para un usuario puntual, el grupo también se tilda
    # desde su ficha.
    group_edit_product_defaults = fields.Boolean(
        string="Permitir editar los valores por defecto",
        implied_group="product_default_settings.group_edit_product_defaults",
    )
    group_show_page_variants = fields.Boolean(
        string="Pestaña Atributos y variantes",
        implied_group="product_default_settings.group_show_page_variants",
    )
    group_show_page_sales = fields.Boolean(
        string="Pestaña Ventas",
        implied_group="product_default_settings.group_show_page_sales",
    )
    group_show_page_purchase = fields.Boolean(
        string="Pestaña Compras",
        implied_group="product_default_settings.group_show_page_purchase",
    )
    group_show_page_inventory = fields.Boolean(
        string="Pestaña Inventario",
        implied_group="product_default_settings.group_show_page_inventory",
    )
    group_show_page_pos = fields.Boolean(
        string="Pestaña Punto de venta",
        implied_group="product_default_settings.group_show_page_pos",
    )
