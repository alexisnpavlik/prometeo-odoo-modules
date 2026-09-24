{
    "name": "Contactos - Aviso de empresa interna",
    "version": "18.0.1.0.0",
    "category": "Hidden",
    "summary": "Banner naranja en ventas, transferencias y facturas cuando el contacto es una empresa propia",
    "description": """
        Muestra una franja naranja "Empresa interna: <nombre>" arriba del formulario de:

        - Pedidos de venta
        - Transferencias (recepciones / entregas)
        - Facturas y notas de crédito

        cuando el contacto elegido es una empresa de este Odoo (res.company) o una
        dirección hija de ella. El aviso aparece apenas se elige el contacto, sin
        necesidad de guardar.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["sale", "stock", "account"],
    "data": [
        "views/sale_order_views.xml",
        "views/stock_picking_views.xml",
        "views/account_move_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
