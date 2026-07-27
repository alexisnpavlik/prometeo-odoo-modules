# -*- coding: utf-8 -*-
{
    "name": "Cuenta Corriente - Retiros de mercadería",
    "version": "18.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Retiros a cuenta corriente con cuotas, pagos, imputación FIFO y dashboard",
    "description": """
        Permite que contactos habilitados retiren mercadería sin pagar en el momento,
        llevando una cuenta corriente propia con cuotas, pagos e imputaciones.

        No genera asientos contables ni comprobantes fiscales: usa modelos propios
        (prefijo caw.) y descuenta stock mediante un albarán de salida.

        El estado del retiro se deriva siempre del estado de sus cuotas: un retiro
        solo figura como pagado cuando TODAS sus cuotas están canceladas.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "stock", "product", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": True,
}
