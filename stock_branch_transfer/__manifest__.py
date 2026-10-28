{
    "name": "Traslados entre sucursales",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Envío y recepción de mercadería entre sucursales (empresas) con aviso de pendientes",
    "description": """
        App "Traslados": una sucursal envía mercadería a otra empresa interna y la
        sucursal destino la recibe (completa o con diferencias).

        - El stock sale del origen al enviar y entra al destino al recibir; lo que
          está en camino vive en la ubicación "Traslados en camino".
        - Recibido con diferencias: entra lo que llegó, el faltante queda en
          tránsito y el sobrante se descuenta del origen. Un manager lo cierra y el
          faltante vuelve al origen.
        - Un manager puede editar o anular cualquier traslado: el stock de las dos
          sucursales se corrige con movimientos nuevos, nunca tocando los hechos.
        - Contador de pendientes sobre el ícono de la app.

        Convive con stock_intercompany: los pickings del módulo no llevan contacto,
        así no se genera la recepción automática del flujo viejo.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["stock", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/stock_location.xml",
        "views/stock_branch_transfer_views.xml",
        "views/branch_transfer_receive_diff_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "stock_branch_transfer/static/src/js/transfer_badge_service.js",
            "stock_branch_transfer/static/src/scss/transfer_badge.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
