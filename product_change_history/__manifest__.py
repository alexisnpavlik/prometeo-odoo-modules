{
    "name": "Product Change History - Historial completo en el chatter",
    "version": "18.0.1.0.0",
    "category": "Inventory/Product",
    "summary": "Registra en el chatter del producto toda edicion de campos (no solo los de tracking nativo)",
    "description": """
Historial completo de modificaciones de productos.

Odoo por defecto solo registra en el chatter los campos que tienen tracking=True.
Este modulo intercepta el write() de product.template y postea en el chatter una
nota con TODOS los campos editados por el usuario (salvo campos tecnicos: magicos
y computados puros), incluyendo relacionales (many2one, many2many, one2many) que el
tracking nativo no cubre.

Formato: una linea por campo cambiado -> "Etiqueta: valor viejo -> valor nuevo".

Ademas registra los ajustes de inventario (stock.quant): al aplicar un ajuste,
postea en el chatter de la plantilla "Ajuste de inventario: cantidad vieja ->
nueva en <ubicacion>".
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["product", "mail", "stock"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
}
