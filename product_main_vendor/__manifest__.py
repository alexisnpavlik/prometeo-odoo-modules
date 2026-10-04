{
    "name": "Product Main Vendor",
    "version": "18.0.1.0.0",
    "category": "Inventory/Purchase",
    "summary": "Campo Proveedor en la ficha de producto, sincronizado con la pestaña Compras.",
    "description": """
Agrega el campo "Proveedor" en la pestaña Información general de la ficha de
producto. No es un dato aparte: lee y escribe la primera línea de proveedores
(seller_ids) de la pestaña Compras, así órdenes de compra y el recomendador de
compras usan el mismo proveedor.

- Elegir un proveedor ya cargado lo sube a primera posición.
- Elegir uno nuevo crea su línea con el costo del producto como precio.
- Vaciar el campo no borra líneas; se gestionan en la pestaña Compras.
""",
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["purchase"],
    "data": ["views/product_template_views.xml"],
    "installable": True,
    "auto_install": False,
    "application": False,
}
