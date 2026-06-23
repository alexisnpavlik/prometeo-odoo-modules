# -*- coding: utf-8 -*-
{
    "name": "POS - Vendedor sin edición de productos/stock",
    "version": "18.0.1.5.0",
    "category": "Point of Sale",
    "summary": "Grupo de seguridad para vendedores POS sin permisos de edición de productos, inventario ni listas de precios",
    "description": """
        Define el grupo "Vendedor POS sin edición de productos/stock" que permite
        operar el punto de venta y ventas (abrir/cerrar sesión, vender, imprimir
        reportes de sesión) pero bloquea con error de acceso:

        - Crear, editar o eliminar productos (nombre, precio, costo, etc.)
        - Ajustes de inventario (stock.quant)
        - Crear, editar o eliminar listas de precios y sus reglas

        La lectura no se restringe, por lo que el POS carga productos y tarifas
        normalmente. El descuento automático de stock del POS funciona porque
        los pickings se validan con sudo. Los usuarios con grupos de Inventario,
        Gerente de Ventas o Administrador no se ven afectados por las reglas,
        incluso si además tienen este grupo asignado. Compatible con multi-compañía.

        Además, este grupo habilita las transferencias intercompañía operadas
        mediante recepciones y entregas: se otorga acceso granular a los pickings
        (stock.picking/move/move.line) y un menú propio "Transferencias" con las
        vistas de Recepciones y Entregas. No se otorga el grupo de Inventario,
        por lo que el bloqueo de catálogo, ajustes de inventario y tarifas se
        mantiene intacto.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "sale_management", "stock"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/stock_transfer_menus.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
