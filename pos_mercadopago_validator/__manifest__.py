{
    "name": "POS Mercado Pago - Validador de cobros por QR",
    "version": "18.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Concilia los pagos del QR estático de Mercado Pago con las líneas de cobro del POS",
    "description": """
Ingesta los pagos que entran a la cuenta de Mercado Pago por el QR estático del
mostrador y se los ofrece al cajero en el momento del cobro, filtrados por monto.
El cajero selecciona el pago recibido y la línea queda cobrada con el pago real
vinculado en la base, con garantía de que un pago no se imputa dos veces.

Incluye aprobación manual auditada para cuando el pago no llega, y visibilidad de
los pagos recibidos que quedaron sin imputar.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/mercadopago_account_views.xml",
        "views/pos_payment_method_views.xml",
        "views/manual_approval_views.xml",
        "views/menus.xml",
        "data/ir_cron.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_mercadopago_validator/static/src/app/*.js",
            "pos_mercadopago_validator/static/src/app/*.xml",
            "pos_mercadopago_validator/static/src/app/*.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
