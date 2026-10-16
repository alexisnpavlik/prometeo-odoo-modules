# -*- coding: utf-8 -*-
{
    "name": "Métricas y Dashboard de Inventario Premium",
    "version": "18.0.2.0.0",
    "category": "Inventory",
    "summary": "Dashboard de inventario: capital inmovilizado, sobrestock, antigüedad de stock y reposición",
    "description": """
        Centro de control de existencias. Detecta qué productos tienen mucho stock y poca venta
        (sin ventas o por encima de la cobertura objetivo), valoriza el capital excedente por producto y
        categoría, muestra la antigüedad del stock desde la última venta y lista los productos a reponer
        con cobertura por sucursal.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["stock", "purchase", "web"],
    "data": [
        "security/security.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "inventory_dashboard_metrics/static/src/css/dashboard.css",
            "inventory_dashboard_metrics/static/src/js/dashboard.js",
            "inventory_dashboard_metrics/static/src/xml/dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
