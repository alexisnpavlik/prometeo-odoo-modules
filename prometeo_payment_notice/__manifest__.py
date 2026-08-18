# -*- coding: utf-8 -*-
{
    "name": "Prometeo - Aviso de pago del servicio",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Muestra un aviso amistoso cuando el pago mensual del servicio no figura registrado",
    "description": """
Consulta una vez por día la API de cobranzas de Prometeo y, si el pago del mes
en curso no figura registrado pasada la fecha límite, muestra una franja
amistosa en la parte superior del cliente web y, opcionalmente, en el POS.

La respuesta se cachea en un parámetro del sistema: ninguna pantalla hace
llamadas de red. Si el servidor no responde se conserva el último estado
conocido y nunca se genera un aviso nuevo.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "web", "point_of_sale"],
    "data": [
        "data/ir_cron.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "prometeo_payment_notice/static/src/css/payment_notice_banner.css",
            "prometeo_payment_notice/static/src/js/payment_notice_banner.js",
            "prometeo_payment_notice/static/src/xml/payment_notice_banner.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
