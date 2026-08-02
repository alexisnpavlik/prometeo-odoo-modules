# -*- coding: utf-8 -*-
{
    "name": "POS Deletion Reason Log",
    "version": "18.0.1.6.3",
    "category": "Point of Sale",
    "summary": "Traza en el POS eliminaciones, descuentos altos y reducciones de precio, pidiendo motivo",
    "description": """
Registra en el backend cada vez que un empleado, en el POS: elimina una orden
completa, borra una línea/producto, reduce la cantidad de una línea, aplica un
descuento por encima del umbral configurado, o baja el precio de una línea.
En cada caso se pide un motivo (lista configurable + texto opcional) y queda
un registro con cajero, producto, cantidad/importe/porcentaje afectado, motivo
y momento — aunque la orden nunca se sincronice al servidor.

Incluye informe de sesión con el detalle y un dashboard de métricas de cajeros.

Standalone: si está instalado pos_special_approval_omax convive con su flujo de
aprobación de manager (los popups se apilan), pero no depende de él.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    # pos_discount es necesario para controlar el descuento global: su patch de
    # apply_discount no llama a super, así que el nuestro tiene que cargar
    # después — la dependencia es la que garantiza ese orden de assets.
    "depends": ["point_of_sale", "web", "pos_discount"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/pos_deletion_reason_data.xml",
        "views/pos_deletion_reason_views.xml",
        "views/pos_control_log_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
        "views/report_saledetails_views.xml",
        "views/dashboard_menu_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_deletion_reason_log/static/src/js/deletion_reason_popup.js",
            "pos_deletion_reason_log/static/src/js/control_logger.js",
            "pos_deletion_reason_log/static/src/js/pos_store.js",
            "pos_deletion_reason_log/static/src/js/order_summary.js",
            "pos_deletion_reason_log/static/src/js/closing_popup.js",
            "pos_deletion_reason_log/static/src/js/control_buttons.js",
            "pos_deletion_reason_log/static/src/xml/deletion_reason_popup.xml",
        ],
        "web.assets_backend": [
            "pos_deletion_reason_log/static/src/css/control_dashboard.css",
            "pos_deletion_reason_log/static/src/js/control_dashboard.js",
            "pos_deletion_reason_log/static/src/xml/control_dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
