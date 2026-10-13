# -*- coding: utf-8 -*-
{
    "name": "Cuenta Corriente de Clientes",
    "version": "18.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Retiros de clientes con recargo, cuotas en vivo y pagos con imputación FIFO",
    "description": """
        Versión simplificada de checking_account_withdrawals pensada para una sola persona.

        Cualquier contacto con DNI puede retirar mercadería: no hace falta habilitarlo.
        Cada retiro define un % de recargo, la cantidad de cuotas, la fecha de la primera
        y la frecuencia; las cuotas se recalculan en pantalla mientras se cargan.

        Al confirmar se valida el albarán de salida (el stock baja en el momento). Los
        pagos se registran directo y se imputan por FIFO a la cuota más vieja; el
        sobrante queda como saldo a favor y se aplica al próximo retiro.

        No genera asientos contables ni comprobantes fiscales.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "stock", "product", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "views/cca_withdrawal_views.xml",
        "views/cca_payment_views.xml",
        "views/cca_wizard_views.xml",
        "views/cca_account_views.xml",
        "views/cca_installment_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        "views/dashboard_views.xml",
        "views/menu_views.xml",
        "report/report_cca_statement.xml",
        "report/report_cca_statement_templates.xml",
        "report/report_cca_payment_receipt.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "customer_checking_account/static/src/css/dashboard.css",
            "customer_checking_account/static/src/js/dashboard.js",
            "customer_checking_account/static/src/xml/dashboard.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
