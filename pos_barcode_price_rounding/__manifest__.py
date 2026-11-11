{
    "name": "POS - Redondeo de precio en código de barra",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "Redondea a múltiplos configurables el precio que trae el código de barra (productos por kilo)",
    "description": """
        Los productos por kilo se etiquetan con un código de barra que trae el
        precio (regla de nomenclatura tipo "Precio"). Ese precio suele tener
        decimales o centenas sueltas.

        Al escanear uno de esos códigos en el POS, el precio de la línea se
        redondea al múltiplo configurado (por defecto 100: 3450 -> 3500).

        Configurable por empresa en Ajustes > Redondeo de precios POS:
        múltiplo y modo (más cercano, hacia arriba, hacia abajo).
        Solo afecta códigos de tipo precio; el resto del POS no cambia.
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
            "pos_barcode_price_rounding/static/src/js/barcode_price_rounding.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
