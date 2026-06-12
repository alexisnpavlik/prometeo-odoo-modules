# -*- coding: utf-8 -*-
{
    "name": "Métricas Gerenciales y Dashboard POS",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Dashboard interactivo premium y métricas gerenciales con Chart.js para análisis de ventas y auditoría de arqueo de cajas",
    "description": """
        Este módulo integra un centro de métricas (Metrics Hub) premium y métricas gerenciales dentro de Odoo.
        Permite a usuarios autorizados analizar el rendimiento de ventas del punto de venta (POS)
        usando visualizaciones modernas, gráficos de evolución, distribución horaria,
        análisis por métodos de pago y auditoría completa de arqueo de cajas.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "web"],
    "data": [
        "security/security.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pos_management_metrics/static/src/css/dashboard.css",
            "pos_management_metrics/static/src/js/dashboard.js",
            "pos_management_metrics/static/src/xml/dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
