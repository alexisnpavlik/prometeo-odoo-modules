# -*- coding: utf-8 -*-
{
    "name": "POS - Asesores de Venta",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Trackeo de asesores de venta: selección en la pantalla de pago, registro en la orden y dashboard de métricas para compensaciones",
    "description": """
        Permite definir asesores de venta, seleccionarlos en la pantalla de pago del POS,
        guardarlos en la orden y analizar sus métricas de venta en un dashboard gerencial
        para el cálculo de compensaciones económicas.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/pos_sales_advisor_views.xml",
        "views/pos_order_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_sales_advisor/static/src/js/payment_screen_patch.js",
            "pos_sales_advisor/static/src/js/ticket_screen_patch.js",
            "pos_sales_advisor/static/src/xml/advisor_button.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
