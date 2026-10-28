# -*- coding: utf-8 -*-
{
    "name": "POS - Promociones",
    "version": "18.0.1.1.0",
    "category": "Sales/Point Of Sale",
    "summary": "App Promociones: precios promocionales por producto o categoría y packs de varios productos a un precio",
    "description": """
        App Promociones en el menú principal, con dos pestañas:

        - Precios: las reglas de la lista de precios principal (la primera por
          secuencia). Producto o categoría obligatorios: una regla sin ninguno
          quedaría para todo el catálogo.
        - Packs: varios productos juntos a un precio (p. ej. Fernet + Coca-Cola),
          sin product_pack ni pos_product_pack. En el POS el pack se activa solo
          cuando la orden tiene todos sus productos (cargados uno por uno, o
          tocando o escaneando el pack, que los agrega). El ahorro se reparte como
          descuento % en esas líneas, que siguen siendo productos normales y
          descuentan su stock.

        En el POS, las líneas con promoción (una regla de Precios que baja el precio
        de venta, o un pack aplicado) llevan la
        etiqueta Promoción y el precio original tachado, también en reglas de
        precio fijo (Odoo solo lo tacha en descuentos %). No marca precios
        editados a mano ni reglas que dejan el precio igual o más alto.
        Reemplaza al módulo pos_promotion_badge.
        Reemplaza a la app Promociones que vivía en web_menu_simplify.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/promotion_price_views.xml",
        "views/promotion_pack_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_promotions/static/src/js/pos_order_line_patch.js",
            "pos_promotions/static/src/js/product_screen_patch.js",
            "pos_promotions/static/src/js/promotion_packs.js",
            "pos_promotions/static/src/xml/orderline.xml",
            "pos_promotions/static/src/scss/orderline.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
