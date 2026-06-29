{
    "name": "POS - Cerrar caja con facturas en borrador",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Permite cerrar la sesión de POS aunque queden facturas en estado borrador",
    "description": """
Permite cerrar la sesión del Punto de Venta aunque alguna factura de las
órdenes haya quedado en estado borrador.

Por defecto, Odoo bloquea el cierre de caja con un UserError cuando hay
facturas sin postear vinculadas a las órdenes de la sesión. Este módulo
neutraliza esa validación: registra en el log las facturas afectadas y
permite continuar con el cierre, dejando las facturas intactas en borrador
para regularizarlas posteriormente.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
}
