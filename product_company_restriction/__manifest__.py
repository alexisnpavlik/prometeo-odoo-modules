{
    "name": "Product Company Restriction",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Restringe la edición de productos a la propia empresa del usuario",
    "description": """
Módulo multicompañía híbrido para catálogo de productos.

Agrega el grupo "Restringido a productos de su empresa". Un usuario con ese
check:
  - Ve los productos globales (company_id vacío) y los de su empresa; no ve los
    de otras empresas (regla multicompañía estándar de Odoo).
  - Solo puede crear/editar/eliminar productos de su propia compañía; tocar un
    producto global o de otra empresa genera AccessError.
  - Al crear un producto se le estampa automáticamente su company_id.

La restricción se aplica a nivel ORM (override de create/write/unlink sobre
product.template y product.product), por lo que es inmune a la combinación OR
de reglas de registro y se mantiene aunque el usuario tenga otros grupos
(Inventario, Ventas, etc.).
""",
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["product"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
