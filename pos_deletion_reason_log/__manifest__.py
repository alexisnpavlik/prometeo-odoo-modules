# -*- coding: utf-8 -*-
{
    "name": "POS Deletion Reason Log",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Pide un motivo y registra eliminaciones de orden, línea o reducción de cantidad en el POS",
    "description": """
Registra en el backend cada vez que un empleado elimina una orden completa,
borra una línea/producto de la orden o reduce la cantidad de una línea en el POS.
Al eliminar se pide un motivo (lista configurable + texto opcional) y queda un
registro con cajero, producto, cantidad, importe, motivo y momento — aunque la
orden nunca se sincronice al servidor.

Standalone: si está instalado pos_special_approval_omax convive con su flujo de
aprobación de manager (los popups se apilan), pero no depende de él.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/pos_deletion_reason_data.xml",
        "views/pos_deletion_reason_views.xml",
        "views/pos_deletion_log_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
        "views/report_saledetails_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_deletion_reason_log/static/src/js/**/*",
            "pos_deletion_reason_log/static/src/xml/**/*",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
