{
    "name": "POS - Venta por importe en productos por peso",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "Ingresar el importe a cobrar y que el POS calcule los kg",
    "description": """
        En escritorio, la tecla Cant. pasa a la fila de botones de arriba (Cliente /
        Acciones / Cant., alineada con el teclado; Nota interna pasa a Acciones) y en su lugar va "Por $".
        En celular "Por $" queda en el popup de Acciones.
        Con una línea de un producto que no se vende por unidad (kg, litro, metro...),
        el cajero ingresa el importe que pide el cliente y el POS fija la cantidad
        = importe / precio unitario mostrado (con impuestos y descuento de la línea),
        redondeada a la precisión de la unidad de medida.
        Como la cantidad se redondea (0,01 kg = 10 g en la configuración actual),
        el precio unitario de la línea se ajusta para que el total sea exactamente
        el importe pedido (queda como precio manual en esa línea).
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_weight_by_amount/static/src/js/weight_by_amount.js",
            "pos_weight_by_amount/static/src/js/product_screen_patch.js",
            "pos_weight_by_amount/static/src/js/control_buttons_patch.js",
            "pos_weight_by_amount/static/src/xml/control_buttons.xml",
            "pos_weight_by_amount/static/src/scss/control_buttons.scss",
        ],
        "web.assets_tests": [
            "pos_weight_by_amount/static/tests/tours/*.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
