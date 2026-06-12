{
    "name": "Stock Picking - Auto cantidad en salidas",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Auto-completa la cantidad hecha = cantidad demandada en albaranes de salida (forzar disponibilidad automática)",
    "description": """
Sobrescribe action_assign() en stock.picking para que, en operaciones de salida
(picking_type_code == 'outgoing'), la cantidad hecha de cada movimiento se iguale
a la cantidad demandada, permitiendo validar la entrega aunque no haya stock
suficiente. Genera cuants negativos en la ubicación de origen.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["stock"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
}
