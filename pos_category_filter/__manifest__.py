{
    "name": "POS - Productos por categoría en cada caja",
    "version": "18.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Cada caja vende solo las categorías de producto que se le configuran",
    "description": """
Reemplaza las Categorías de PdV por la categoría de producto:
- En cada caja se elige Todos / Solo estas categorías / Todas menos estas.
- La caja descarga solo los productos permitidos (subcategorías incluidas).
- Escanear o buscar un producto excluido no lo agrega al pedido.
- Se ocultan la barra de categorías del POS y las Categorías de PdV.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
    "application": False,
}
