# -*- coding: utf-8 -*-
{
    "name": "POS - Promoción visible en la línea",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "Marca con la etiqueta Promoción y el precio original tachado las líneas con una regla de lista de precios",
    "description": """
        Cuando a una línea del POS le aplica una regla de la lista de precios
        (las Promociones de web_menu_simplify) y el precio queda por debajo del
        precio de venta del producto, la línea muestra:

        - La etiqueta Promoción.
        - El precio de venta original tachado, también en reglas de precio fijo
          (Odoo solo lo tacha en reglas de descuento %).

        No marca precios editados a mano ni reglas que dejan el precio igual o
        por encima del de venta (p. ej. bases con precio de venta de relleno).
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_promotion_badge/static/src/js/pos_order_line_patch.js",
            "pos_promotion_badge/static/src/xml/orderline.xml",
            "pos_promotion_badge/static/src/scss/orderline.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
