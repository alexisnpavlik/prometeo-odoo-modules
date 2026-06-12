{
    "name": "POS - Facturar destildado por defecto",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Evita que 'Facturar' quede tildado por defecto al elegir un cliente empresa",
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "l10n_ar_pos"],
    "data": [],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_invoice_default_off/static/src/js/pos_order_patch.js",
            "pos_invoice_default_off/static/src/js/payment_screen_patch.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
