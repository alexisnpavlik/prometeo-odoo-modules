# -*- coding: utf-8 -*-
{
    "name": "Cambios de Precio para Góndola",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Lista operativa de productos con precio cambiado recientemente para actualizar etiquetas en góndola",
    "description": """
        Registra cada cambio de precio de venta (global) y de listas de precios,
        y muestra a cada sucursal una lista de trabajo con los productos que
        cambiaron de precio recientemente, para actualizar las etiquetas en la
        góndola. Cada fila se marca como pendiente/actualizado por sucursal.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["product", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "product_price_change_metrics/static/src/css/dashboard.css",
            "product_price_change_metrics/static/src/js/dashboard.js",
            "product_price_change_metrics/static/src/xml/dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
