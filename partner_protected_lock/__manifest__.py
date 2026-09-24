{
    "name": "Contactos - Bloqueo de empresas internas y Consumidor Final",
    "version": "18.0.1.0.0",
    "category": "Hidden",
    "summary": "Impide editar, archivar o borrar los contactos de las empresas propias y Consumidor Final Anónimo",
    "description": """
        Protege contactos que no deberían tocarse en la operación diaria:

        - Consumidor Final Anónimo (l10n_ar.par_cfa)
        - El contacto de cada empresa de este Odoo (res.company.partner_id), incluidas las futuras

        Solo los administradores (grupo Ajustes) pueden modificarlos. El bloqueo
        aplica desde cualquier lugar (formulario, POS, importaciones). Los procesos
        internos que corren con sudo no se ven afectados. Las direcciones hijas de
        una empresa (entrega, facturación) se editan normalmente.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "l10n_ar"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
}
