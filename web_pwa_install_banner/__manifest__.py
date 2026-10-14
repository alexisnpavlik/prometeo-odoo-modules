{
    "name": "Web - Banner para instalar como app",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "Muestra en el móvil un cartel \"Instalar app\" para agregar el ERP a la pantalla de inicio",
    "description": """
        Odoo 18 ya es una PWA instalable, pero la opción "Instalar app" solo
        aparece escondida en el menú de usuario. Este módulo agrega un banner
        visible abajo en pantallas chicas con los botones "Instalar" y "Ahora no".

        - Usa el servicio pwa nativo: en Chrome/Android dispara el diálogo nativo;
          en Safari/iOS muestra las instrucciones de "Agregar a pantalla de inicio".
        - No aparece si la app ya está instalada (modo standalone) ni si el usuario
          lo descartó (se recuerda en el navegador).
        - Requiere HTTPS (o localhost) para que el navegador permita instalar.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "web_pwa_install_banner/static/src/js/install_banner.js",
            "web_pwa_install_banner/static/src/xml/install_banner.xml",
            "web_pwa_install_banner/static/src/scss/install_banner.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
