# -*- coding: utf-8 -*-
{
    "name": "Métricas de Caja",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Caja del día: ventas por cajero, efectivo en caja, retiros, diferencias al cierre y medios de pago",
    "description": """
        Dashboard para el dueño del negocio: cuánto se vendió y cobró en el período, cuánto
        efectivo hay en las cajas abiertas, qué cajero rinde mejor (como vendedor y como
        responsable de caja), retiros e ingresos de efectivo, diferencias al cierre y
        medios de pago agrupados.
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
            "pos_cash_metrics/static/src/css/dashboard.css",
            "pos_cash_metrics/static/src/js/dashboard.js",
            "pos_cash_metrics/static/src/xml/dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
