{
    "name": "Conteo de stock por código de barras",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Conteo de inventario escaneando códigos de barras con la cámara del teléfono",
    "description": """
Conteo de stock por código de barras
====================================

Permite contar el stock de una ubicación escaneando los códigos de barras con la
cámara del teléfono (o con un lector láser en la PC).

Flujo:
  1. Se crea una sesión de conteo con empresa y ubicación.
  2. Se escanea cada producto y se carga la cantidad real contada.
  3. Al aplicar, las cantidades contadas se escriben como ajuste de inventario
     nativo de Odoo (inventory_quantity + action_apply_inventory).

El conteo es siempre parcial: los productos que no se escanean no se tocan.
Los productos con lotes, series o múltiples quants en la ubicación se rechazan
con error en vez de producir un total incorrecto.

Crear y cargar sesiones requiere Inventario/Usuario; aplicarlas requiere
Inventario/Administrador.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["stock", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "views/stock_count_session_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "stock_count_barcode/static/src/js/scan_button.js",
            "stock_count_barcode/static/src/xml/scan_button.xml",
            "stock_count_barcode/static/src/scss/stock_count.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
