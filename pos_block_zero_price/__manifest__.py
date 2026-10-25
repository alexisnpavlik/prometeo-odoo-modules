# -*- coding: utf-8 -*-
{
    "name": "POS - Bloquear venta con precio $0",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "No deja cobrar una orden del POS que tenga productos con precio unitario $0",
    "description": """
        Red de seguridad contra vender gratis por error: un producto sin precio de
        venta o una regla de lista de precios mal cargada (p. ej. "Todos los
        productos" a precio fijo $0).

        Al tocar Pago, y otra vez al validar el pago, si alguna línea tiene precio
        unitario $0 el POS muestra qué productos son y no deja seguir.

        No cuenta: devoluciones, líneas de combo (el precio va en el combo) ni
        descuentos aplicados sobre un precio mayor a $0.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_block_zero_price/static/src/js/pos_block_zero_price.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
