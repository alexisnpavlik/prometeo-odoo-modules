# -*- coding: utf-8 -*-
{
    "name": "POS Global Surcharge Button",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "Botón de recargo porcentual global en la pantalla principal del POS.",
    "description": """
        Agrega un botón 'Recargo' en la pantalla principal del POS, junto al de
        Descuento. Funciona como toggle: un toque aplica el porcentaje de recargo
        configurado (20% por defecto) como una línea de producto positiva sobre la
        base del pedido; otro toque la quita. El porcentaje y el producto de recargo
        se configuran en los Ajustes del POS.
    """,
    "author": "Alexis",
    "depends": ["point_of_sale", "pos_discount", "pos_global_discount_button"],
    "data": [
        "data/surcharge_product.xml",
        "views/res_config_settings_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
