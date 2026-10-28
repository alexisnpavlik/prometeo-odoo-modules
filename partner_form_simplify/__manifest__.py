{
    "name": "Contactos - Ficha simplificada",
    "version": "18.0.1.1.0",
    "category": "Hidden",
    "summary": "Oculta campos que no se usan en la ficha de contacto y pone valores por defecto argentinos",
    "description": """
        Simplifica la ficha de contacto:

        - Oculta las secciones AFIP y Otros (ingresos brutos, DREI) de Datos Fiscales.
        - Oculta Nombre de la empresa (para personas), Calle 2 y Teléfono (queda Móvil).
        - Contactos nuevos: país Argentina y DNI para personas y CUIT para empresas (editable).

        Solo cambia la vista: los datos existentes no se tocan.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["l10n_ar_ux", "l10n_ar_tax"],
    "data": ["views/res_partner_views.xml"],
    "installable": True,
    "auto_install": False,
    "application": False,
}
