# -*- coding: utf-8 -*-
{
    "name": "Recomendador de compra - Suavizado exponencial",
    "version": "18.0.1.0.1",
    "category": "Inventory/Purchase",
    "summary": "Agrega el método de estimación EWMA al recomendador de compra",
    "description": """
        Suma un segundo método de estimación de demanda al recomendador:
        promedio móvil exponencialmente ponderado (EWMA).

        A diferencia del promedio ponderado por ventanas, que trata igual a
        todos los días dentro de una misma ventana, el EWMA le da más peso a
        cada día más reciente de forma continua. Reacciona más rápido a un
        cambio de ritmo de venta y es más nervioso ante el ruido.

        Este módulo existe también como prueba de la arquitectura: agrega un
        método sin modificar una sola línea del módulo base.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["prometeo_purchase_advisor"],
    "data": ["views/demand_model_views.xml"],
    "installable": True,
    "auto_install": False,
    "application": False,
}
