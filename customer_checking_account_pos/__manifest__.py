# -*- coding: utf-8 -*-
{
    "name": "Cuenta Corriente de Clientes - Punto de Venta",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Vende a cuenta corriente y cobra cuotas desde el POS del kiosco",
    "description": """
        Puente entre customer_checking_account y el punto de venta.

        Un método de pago del POS marcado como "Cuenta corriente" convierte la venta en un
        retiro a cuenta del cliente (con recargo y cuotas configurables en Ajustes), y el
        producto "Pago Cuenta Corriente" permite cobrar cuotas desde la misma caja.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["customer_checking_account", "point_of_sale"],
    "data": [
        "data/product_data.xml",
        "views/res_config_settings_views.xml",
        "views/pos_payment_method_views.xml",
        "views/cca_withdrawal_views.xml",
    ],
    "installable": True,
    "auto_install": True,
    "application": False,
}
