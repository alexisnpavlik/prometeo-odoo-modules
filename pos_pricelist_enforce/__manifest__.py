# -*- coding: utf-8 -*-
{
    "name": "POS - Forzar precio de lista al cobrar",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "Corrige el bug intermitente del POS que deja líneas a precio "
               "público en vez del fijo de la lista de precios.",
    "description": """
        Red de seguridad para un bug conocido de Odoo POS (sin fix oficial):
        de forma intermitente el POS no aplica la lista de precios a la orden y
        las líneas quedan al precio público (lst_price) en vez del fijo de la
        regla, generando sobrecobros/subcobros silenciosos.

        Este módulo, ANTES de ir a cobrar, re-aplica el precio de la lista a las
        líneas de producto que quedaron a público. Actúa solo del lado del
        frontend (antes del pago, para no descuadrar la caja) y de forma
        quirúrgica:

          - Solo reglas de lista de tipo 'precio fijo' con valor > 0
            (respeta las reglas en 0 = queda a público).
          - No toca precios editados a mano, líneas de descuento/recargo,
            combos ni devoluciones.
          - Opcionalmente avisa al cajero cuando corrige alguna línea.

        Configurable por punto de venta en Ajustes del POS.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_pricelist_enforce/static/src/js/pos_order_patch.js",
            "pos_pricelist_enforce/static/src/js/pos_store_patch.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
