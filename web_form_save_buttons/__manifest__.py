{
    "name": "Web - Botones Guardar y Descartar grandes",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "Reemplaza los íconos de guardar/descartar del formulario por botones grandes con texto",
    "description": """
        En los formularios, Odoo 18 muestra guardar y descartar como dos íconos
        chicos (nube y cruz) junto al título. Este módulo los convierte en
        botones grandes con texto: "Guardar" (color principal) y "Descartar".

        Se mantienen los atajos de teclado (Alt+S / Alt+J) y siguen apareciendo
        solo cuando hay cambios sin guardar o el registro es nuevo.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "web_form_save_buttons/static/src/xml/form_status_indicator.xml",
            "web_form_save_buttons/static/src/scss/form_status_indicator.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
