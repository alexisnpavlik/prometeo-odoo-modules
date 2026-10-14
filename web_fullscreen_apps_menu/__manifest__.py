{
    "name": "Web - Menú de apps a pantalla completa",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "El botón de apps abre una grilla a pantalla completa con íconos grandes, como en versiones anteriores de Odoo",
    "description": """
        Reemplaza el desplegable de apps de Odoo 18 Community por una pantalla
        completa con íconos grandes (96px en escritorio, 72px en el teléfono).
        En el teléfono reemplaza también la barra lateral. Se cierra con Escape,
        tocando el fondo o eligiendo una app.

        Para volver al desplegable original, desinstalar el módulo.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "web_fullscreen_apps_menu/static/src/js/home_menu.js",
            "web_fullscreen_apps_menu/static/src/xml/home_menu.xml",
            "web_fullscreen_apps_menu/static/src/scss/home_menu.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
