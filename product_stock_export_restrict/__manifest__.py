# -*- coding: utf-8 -*-
{
    "name": "Productos/Stock - Restringir exportación",
    "version": "18.0.1.0.1",
    "category": "Inventory/Inventory",
    "summary": "Oculta Exportar en productos y stock para usuarios sin el grupo de exportación",
    "description": """
        Oculta en la interfaz las opciones para exportar productos y stock a archivo:

        - "Exportar" del menú de acciones y "Exportar todo" del engranaje en las listas.
        - "Descargar xlsx" de la vista pivote.
        - Los botones "Exportar Excel" del dashboard de inventario (inventory_dashboard_metrics).

        Modelos cubiertos: product.template, product.product, stock.quant, stock.move,
        stock.move.line y product.supplierinfo. El resto de las exportaciones no cambia.

        Solo los usuarios del grupo "Puede exportar productos/stock" ven esas opciones.
        Nadie lo tiene por defecto, tampoco el administrador: se asigna a mano.

        Es una restricción de interfaz: no bloquea /web/export en el servidor.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web", "product", "stock"],
    "data": [
        "security/security.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "product_stock_export_restrict/static/src/js/export_restrict.js",
        ],
        "web.assets_backend_lazy": [
            "product_stock_export_restrict/static/src/js/pivot_export_restrict.js",
            "product_stock_export_restrict/static/src/xml/pivot_buttons.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
