{
    "name": "Prometeo ERP - Marca",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "Reemplaza la marca Odoo por Prometeo ERP: nombre, logos, favicon y enlaces",
    "description": """
        Quita las referencias visibles a Odoo y las reemplaza por Prometeo ERP
        (https://prometeo.com.ar/).

        - Título de pestaña, favicon, íconos de la app instalable (PWA) y página offline.
        - Login: "Powered by" apunta a Prometeo y se oculta el enlace al gestor de bases.
        - Menú de usuario: se quitan Documentación, Soporte y "Mi cuenta Odoo.com";
          se agrega un acceso a la web de Prometeo.
        - Títulos de los diálogos de error y de sesión expirada.
        - Ajustes: bloque de versión/edición y nombre por defecto de la app.
        - Emails: pie "Powered by" de los layouts, resumen periódico (digest) y
          plantillas de invitación/registro.
        - Punto de venta: logo de la barra, salvapantallas, ticket, pantalla del
          cliente, título y favicon.
        - OdooBot pasa a llamarse PrometeoBot con el ícono de Prometeo.

        Los cambios de datos (plantillas de email, OdooBot, nombre de la app) se
        aplican al instalar y no se revierten al desinstalar.
    """,
    "author": "Alexis Medina",
    "website": "https://prometeo.com.ar/",
    "license": "LGPL-3",
    "depends": ["web", "base_setup", "mail", "digest", "point_of_sale"],
    "data": [
        "views/webclient_templates.xml",
        "views/mail_templates.xml",
        "views/digest_templates.xml",
        "views/point_of_sale_templates.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web._assets_core": [
            "prometeo_branding/static/src/js/title_service.js",
            "prometeo_branding/static/src/js/error_dialogs.js",
            "prometeo_branding/static/src/xml/core_templates.xml",
        ],
        "web.assets_backend": [
            "prometeo_branding/static/src/js/user_menu_items.js",
            "prometeo_branding/static/src/xml/webclient_templates.xml",
        ],
        "point_of_sale._assets_pos": [
            "prometeo_branding/static/src/xml/pos_templates.xml",
            "prometeo_branding/static/src/xml/pos_logo.xml",
        ],
        "point_of_sale.customer_display_assets": [
            "prometeo_branding/static/src/xml/pos_logo.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
    "application": False,
}
