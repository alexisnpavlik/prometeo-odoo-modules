# -*- coding: utf-8 -*-
{
    "name": "POS - Vendedor sin edición de productos/stock (con visualización de stock)",
    "version": "18.0.1.4.0",
    "category": "Point of Sale",
    "summary": "Grupo de seguridad para vendedores POS sin permisos de edición de productos, inventario ni listas de precios, pero con visualización de unidades de stock",
    "description": """
        Define el grupo "Vendedor POS sin edición de productos/stock (con visualización de stock)" que permite
        operar el punto de venta y ventas (abrir/cerrar sesión, vender, imprimir
        reportes de sesión) pero bloquea con error de acceso:

        - Crear, editar o eliminar productos (nombre, precio, costo, etc.)
        - Ajustes de inventario (crear, escribir o eliminar stock.quant)
        - Crear, editar o eliminar listas de precios y sus reglas

        A diferencia de pos_user_readonly, este grupo permite visualizar la cantidad
        de unidades de stock (leer stock.quant), posibilitando consultar existencias.
        La lectura de catálogo y tarifas tampoco se restringe, por lo que el POS carga 
        productos y tarifas normalmente. El descuento automático de stock del POS funciona porque
        los pickings se validan con sudo. Los usuarios con grupos de Inventario,
        Gerente de Ventas o Administrador no se ven afectados por las reglas,
        incluso si además tienen este grupo asignado. Compatible con multi-compañía.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "sale_management", "stock"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
