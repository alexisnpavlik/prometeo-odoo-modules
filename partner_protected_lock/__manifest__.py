{
    "name": "Bloqueo de contactos internos, Consumidor Final y productos Descuento/Recargo",
    "version": "18.0.1.1.0",
    "category": "Hidden",
    "summary": "Impide editar, archivar o borrar los contactos de las empresas propias, Consumidor Final Anónimo y los productos de descuento y recargo del POS",
    "description": """
        Protege contactos que no deberían tocarse en la operación diaria:

        - Consumidor Final Anónimo (l10n_ar.par_cfa)
        - El contacto de cada empresa de este Odoo (res.company.partner_id), incluidas las futuras
        - Los productos de descuento global y de recargo de cada caja del POS
          (pos.config.discount_product_id / surcharge_product_id). No depende del POS
          ni del módulo de recargo: protege sólo los campos que existan en la base.

        Solo los administradores (grupo Ajustes) pueden modificarlos. El bloqueo
        aplica desde cualquier lugar (formulario, POS, importaciones). Los procesos
        internos que corren con sudo no se ven afectados. Las direcciones hijas de
        una empresa (entrega, facturación) se editan normalmente.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "l10n_ar", "product"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
}
