# -*- coding: utf-8 -*-
{
    "name": "POS - Promociones",
    "version": "18.0.2.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "App Promociones: packs de uno o varios productos a un precio",
    "description": """
        App Promociones en el menú principal: abre directo en Packs.

        Un pack es uno o varios productos juntos a un precio (p. ej. Fernet +
        Coca-Cola, o un solo producto en oferta), sin product_pack ni
        pos_product_pack. En el POS el pack se activa solo cuando la orden tiene
        todos sus productos (cargados uno por uno, o tocando o escaneando el pack,
        que los agrega). El ahorro se reparte como descuento % en esas líneas, que
        siguen siendo productos normales y descuentan su stock, y llevan la
        etiqueta Promoción.

        Desde 18.0.2.0.0 ya no gestiona reglas de listas de precios (la vieja
        pestaña Precios): las reglas que existan son reglas normales de Odoo.
        Reemplaza al módulo pos_promotion_badge.
        Reemplaza a la app Promociones que vivía en web_menu_simplify.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
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
