{
    "name": "Web - Menús simplificados",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "Oculta menús avanzados, botones de producto y chat/actividades, configurable desde Ajustes",
    "description": """
        Simplifica la interfaz para usuarios no técnicos (kiosco, personas mayores).

        Desde Ajustes > Interfaz simplificada hay un interruptor por cada cosa
        que se oculta, agrupados en General, Punto de venta, Facturación,
        Inventario y Productos. Todos vienen activados.

        Fijo, sin interruptor:

        - Ajustes y Aplicaciones quedan visibles solo para el administrador.
        - Punto de venta va primero en el menú y es la app que abre al iniciar
          sesión (FIRST_MENU_XMLIDS).
        - El administrador en modo debug (?debug=1) ve todos los menús.
        - Punto de venta > Órdenes > Facturas abre las facturas de cliente, para
          poder ocultar la app Facturación sin perder el acceso.

        Los menús se filtran en código sobre ir.ui.menu, no desactivando
        registros: actualizar stock/account/mail no los vuelve a mostrar.
        Los xmlids de módulos no instalados se ignoran.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web", "mail", "product", "account", "point_of_sale"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/pos_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "web_menu_simplify/static/src/js/systray_cleanup.js",
            "web_menu_simplify/static/src/scss/chat_hub_hidden.scss",
            "web_menu_simplify/static/src/js/home_menu.js",
            "web_menu_simplify/static/src/xml/home_menu.xml",
            "web_menu_simplify/static/src/scss/home_menu.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
