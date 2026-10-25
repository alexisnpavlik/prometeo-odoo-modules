{
    "name": "POS - Ingresos y retiros con otros métodos de pago",
    "version": "18.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Ingresos y retiros del POS con cualquier método de pago, no solo efectivo",
    "description": """
        El popup de Ingreso/Retiro del POS suma un selector de método de pago.
        Además del efectivo, aparecen los métodos marcados con
        "Permitir ingresos/retiros" en su configuración.

        El movimiento se registra como línea de extracto en el diario del
        método, ligado a la sesión por un campo propio (no pos_session_id),
        para no mezclarse con el arqueo de efectivo. En el cierre de sesión, el
        esperado de cada método incluye sus ingresos y retiros.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "views/pos_payment_method_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_cash_move_payment_methods/static/src/js/cash_move_popup.js",
            "pos_cash_move_payment_methods/static/src/xml/cash_move_popup.xml",
            "pos_cash_move_payment_methods/static/src/xml/closing_popup.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
