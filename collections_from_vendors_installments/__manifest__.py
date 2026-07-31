# -*- coding: utf-8 -*-
{
    "name": "Cobranza a vendedores y cuotas",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Venta domiciliaria en cuotas: entrega al vendedor, tarjeta, enrutamiento y cobranza",
    "description": """
        Soporta el circuito de venta domiciliaria financiada de una fábrica de muebles.

        El vendedor retira mercadería de fábrica, la vende en cuotas en el domicilio del
        cliente y cobra la primera cuota como comisión. Luego enruta la tarjeta a un
        cobrador, que la acepta y gestiona la cobranza de las cuotas restantes.

        No genera asientos contables ni comprobantes fiscales: usa modelos propios
        (prefijo cvi.). El stock en poder de cada vendedor se lleva con ubicaciones
        internas nativas de Odoo, una por vendedor.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "base_setup", "mail", "stock", "product", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/stock_location.xml",
        "data/ir_cron.xml",
        "views/cvi_card_views.xml",
        "views/cvi_installment_views.xml",
        "views/cvi_payment_views.xml",
        "views/cvi_wizard_views.xml",
        "views/stock_quant_views.xml",
        "views/stock_picking_views.xml",
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "collections_from_vendors_installments/static/src/js/*.js",
            "collections_from_vendors_installments/static/src/xml/*.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
