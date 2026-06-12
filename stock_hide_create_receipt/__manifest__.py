# -*- coding: utf-8 -*-
{
    "name": "Ocultar Crear Recepción en Inventario",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Oculta el botón de crear nuevas recepciones en el flujo de inventario.",
    "description": """
        Módulo simple para ocultar el botón 'Crear' / 'Nuevo' en las recepciones de inventario.
        Esto aplica tanto para el menú de Operaciones -> Recepciones como para los accesos
        desde el tablero (Dashboard) de Inventario.
    """,
    "author": "Alexis Medina",
    "license": "LGPL-3",
    "depends": ["stock"],
    "data": [
        "views/stock_picking_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
