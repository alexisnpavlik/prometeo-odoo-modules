{
    "name": "Mail - Ocultar Conversaciones",
    "version": "18.0.1.0.0",
    "category": "Productivity/Discuss",
    "summary": "Oculta y bloquea el acceso a la aplicación Conversaciones",
    "description": """
        Oculta la aplicación Conversaciones para todos los usuarios y bloquea
        su apertura mediante enlaces directos, sin afectar el chatter ni las
        actividades disponibles en otros módulos.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["mail", "web"],
    "data": [
        "views/mail_menu_views.xml",
    ],
    "uninstall_hook": "uninstall_hook",
    "installable": True,
    "auto_install": False,
    "application": False,
}
