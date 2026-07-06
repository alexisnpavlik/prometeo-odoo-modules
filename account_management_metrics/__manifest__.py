# -*- coding: utf-8 -*-
{
    "name": "Métricas de Facturación y Dashboard Contable",
    "version": "18.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Dashboard interactivo de facturación con Chart.js: comprobantes por tipo, sucursales, medios de pago, borradores, canceladas y notas de crédito",
    "description": """
        Este módulo integra un centro de métricas de facturación dentro de Odoo.
        Permite a usuarios autorizados analizar la emisión de comprobantes de venta:
        facturación total por empresa y por sucursal (diario/punto de venta),
        cobros por medio de pago, cantidad de comprobantes emitidos por tipo
        (Factura A, B, C, Notas de Crédito, etc.), facturas en borrador y canceladas.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["account", "l10n_latam_invoice_document", "web"],
    "data": [
        "security/security.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "account_management_metrics/static/src/css/dashboard.css",
            "account_management_metrics/static/src/js/dashboard.js",
            "account_management_metrics/static/src/xml/dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
