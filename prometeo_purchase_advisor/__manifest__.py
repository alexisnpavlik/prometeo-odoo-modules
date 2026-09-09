# -*- coding: utf-8 -*-
{
    "name": "Prometeo - Recomendador de compra",
    "version": "18.0.1.1.1",
    "category": "Inventory/Purchase",
    "summary": "Sugerencias de compra a partir de la demanda real observada, revisables y convertibles en órdenes de compra",
    "description": """
        Calcula cuánto comprar de cada producto a partir de la demanda real:
        lee los movimientos de stock hacia ubicaciones de cliente, estima la
        demanda diaria promedio por producto y almacén, y sugiere una cantidad
        que contempla lead time medido del proveedor, stock actual, mercadería
        en tránsito y variabilidad de la demanda.

        La sugerencia no es automática: el usuario la revisa, edita cantidades,
        agrega o quita productos, y recién entonces genera las órdenes de compra
        en borrador agrupadas por proveedor.

        Lee de stock.move, no de las líneas de venta: unifica POS, ventas
        normales y entregas manuales sin depender de qué canal se usó.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "product", "stock", "purchase_stock"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/demand_model_data.xml",
        "data/ir_cron.xml",
        "views/demand_model_views.xml",
        "views/demand_model_rule_views.xml",
        "views/purchase_suggestion_views.xml",
        "views/product_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": True,
}
