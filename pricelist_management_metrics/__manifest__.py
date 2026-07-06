# -*- coding: utf-8 -*-
{
    "name": "Métricas de Precios por Sucursal",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "Dashboard comparativo de precios base vs listas de precios por sucursal/empresa con Chart.js",
    "description": """
        Este módulo integra un dashboard premium para auditar los precios de venta entre sucursales.
        Compara el precio base de cada producto contra los precios definidos en las listas de precios
        de cada sucursal/empresa. Si existe un precio de lista definido, ese es el precio vigente
        en esa sucursal. Incluye tabla comparativa filtrable por producto/categoría y gráfico
        de los productos con mayor diferencia de precios.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["product", "web"],
    "data": [
        "security/security.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pricelist_management_metrics/static/src/css/dashboard.css",
            "pricelist_management_metrics/static/src/js/dashboard.js",
            "pricelist_management_metrics/static/src/xml/dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
