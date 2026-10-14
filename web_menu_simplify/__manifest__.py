{
    "name": "Web - Menús simplificados",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "Oculta menús avanzados, botones de producto y chat/actividades, configurable desde Ajustes",
    "description": """
        Simplifica la interfaz para usuarios no técnicos (kiosco, personas mayores).

        Desde Ajustes > Interfaz simplificada hay un interruptor por cada cosa
        que se oculta, agrupados en General, Compras, Punto de venta,
        Facturación, Inventario y Productos. Todos vienen activados.

        Fijo, sin interruptor:

        - Ajustes y Aplicaciones quedan visibles solo para el administrador.
        - Punto de venta va primero en el menú y es la app que abre al iniciar
          sesión (FIRST_MENU_XMLIDS).
        - El administrador en modo debug (?debug=1) ve todos los menús.
        - Punto de venta > Órdenes > Facturas abre las facturas de cliente, para
          poder ocultar la app Facturación sin perder el acceso.
        - Inventario > Categorías, acceso directo a las categorías.
        - Reabastecer: ruta siempre Comprar (solo el admin la cambia) y Proveedor
          como contacto, que se puede crear desde el asistente.
        - Orden de compra: Confirmar e ingresar en un paso, Imprimir y Devolver
          (la devolución se valida al confirmarla).
        - Renombra al español las ubicaciones de stock que quedaron en inglés
          (Partners/Customers, Virtual Locations/Inventory adjustment, etc.).

        Los menús se filtran en código sobre ir.ui.menu, no desactivando
        registros: actualizar stock/account/mail no los vuelve a mostrar.
        Los xmlids de módulos no instalados se ignoran.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web", "mail", "product", "account", "point_of_sale", "stock", "purchase", "purchase_stock"],
    "data": [
        "data/stock_location_data.xml",
        "views/res_config_settings_views.xml",
        "views/pos_menus.xml",
        "views/stock_menus.xml",
        "views/purchase_menus.xml",
        "views/purchase_order_views.xml",
        "views/product_replenish_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "web_menu_simplify/static/src/js/systray_cleanup.js",
            "web_menu_simplify/static/src/scss/chat_hub_hidden.scss",
            "web_menu_simplify/static/src/scss/product_form.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
