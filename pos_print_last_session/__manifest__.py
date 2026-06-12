# -*- coding: utf-8 -*-
{
    "name": "POS - Imprimir última sesión cerrada",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Botón en el recuadro de cada caja del dashboard POS para imprimir el reporte de la última sesión cerrada",
    "description": """
        Agrega un botón en la tarjeta kanban de cada caja (dashboard de Punto
        de Venta) que imprime el reporte "Detalles de ventas" de la última
        sesión cerrada de esa caja. El botón solo se muestra si la caja tiene
        al menos una sesión cerrada.
    """,
    "author": "Alexis",
    "depends": ["point_of_sale"],
    "data": [
        "views/pos_config_kanban.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
