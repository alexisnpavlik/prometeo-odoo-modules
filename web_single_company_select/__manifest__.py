{
    "name": "Web - Una sola empresa a la vez",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "El selector de empresas permite elegir una sola empresa activa por vez",
    "description": """
Evita que los usuarios trabajen con dos o más empresas seleccionadas sin querer.

- El selector de empresas de la barra superior (y el del menú móvil) pasa a
  funcionar como un botón de opción: tocar el casillero o el nombre de una
  empresa entra a esa empresa sola.
- Se quita el "Seleccionar todas".
- Si el navegador arranca con varias empresas guardadas (cookie ``cids`` o
  URL vieja), queda solo la primera.
- Cuando Odoo cambia de empresa automáticamente al abrir un registro de otra
  empresa, entra a esa empresa en lugar de sumarla a las activas.
""",
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "web_single_company_select/static/src/js/single_company.js",
            "web_single_company_select/static/src/xml/switch_company_menu.xml",
        ],
        "web.assets_unit_tests": [
            "web_single_company_select/static/tests/**/*",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
