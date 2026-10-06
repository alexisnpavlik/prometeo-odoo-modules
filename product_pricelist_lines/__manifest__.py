{
    "name": "Product Pricelist Lines",
    "version": "18.0.1.0.5",
    "category": "Sales/Sales",
    "summary": "Tabla de listas de precios y su precio en la ficha de producto.",
    "description": """
Agrega en la pestaña Información general de la ficha de producto una tabla
editable con las listas de precios que aplican al producto y su precio.

No es un dato aparte: cada fila es una regla de precio fijo de la lista
(product.pricelist.item aplicada al producto), la misma que se ve desde
Ventas > Listas de precios y la que usa el POS.

- Solo muestra reglas de precio fijo aplicadas al producto completo; las de
  variante, categoría, globales o por fórmula se gestionan desde la lista.
- Muestra las listas de todas las empresas del usuario, no solo las tildadas
  en el selector de empresas.
- Excluye las listas "Predeterminado" (la que Odoo crea en cada empresa).
- Agregar una fila crea la regla en la lista elegida; borrarla la elimina.
""",
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["product"],
    "data": ["views/product_template_views.xml"],
    "assets": {
        "web.assets_backend": [
            "product_pricelist_lines/static/src/js/pricelist_many2one_field.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
