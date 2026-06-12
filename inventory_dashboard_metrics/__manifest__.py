# -*- coding: utf-8 -*-
{
    "name": "Métricas y Dashboard de Inventario Premium",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Dashboard interactivo en tiempo real con Chart.js para análisis de valoración de stock, rotación y alertas críticas",
    "description": """
        Este módulo integra un centro de control analítico para la gestión de existencias.
        Permite a usuarios autorizados visualizar la valoración económica del inventario por categoría,
        la velocidad de rotación de productos basándose en movimientos de stock físicos (stock.move) de los últimos 30 días,
        y un centro de control y alertas de stock crítico o quiebres de existencias con buscador dinámico en tiempo real.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["stock", "web"],
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
