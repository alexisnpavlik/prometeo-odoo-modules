# -*- coding: utf-8 -*-
{
    "name": "POS - Promociones",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "App Promociones: precios promocionales por producto o categoría y packs de varios productos a un precio",
    "description": """
        App Promociones en el menú principal, con dos pestañas:

        - Precios: las reglas de la lista de precios principal (la primera por
          secuencia). Producto o categoría obligatorios: una regla sin ninguno
          quedaría para todo el catálogo.
        - Packs: varios productos juntos a un precio (p. ej. Fernet + Coca-Cola).
          Se arman como combos nativos de Odoo, sin product_pack ni
          pos_product_pack: en el POS se agregan con un toque, el precio se
          reparte entre los productos y cada uno descuenta su stock.

        Trae pos_promotion_badge, que marca en el POS las líneas con promoción.
        Reemplaza a la app Promociones que vivía en web_menu_simplify.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "pos_promotion_badge"],
    "data": [
        "security/ir.model.access.csv",
        "views/promotion_price_views.xml",
        "views/promotion_pack_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": True,
}
