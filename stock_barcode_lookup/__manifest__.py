{
    "name": "Escáner de productos",
    "version": "18.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "App para buscar un producto escaneando su código de barras con la cámara",
    "description": """
        App "Escáner" en el panel principal. Un botón grande escanea el código
        de barras y muestra el producto (foto, precio, stock, proveedor) con
        accesos a Abrir ficha, Reabastecer o Escanear otro. Si el código no
        existe, ofrece crear el producto con ese código.

        Cámara: con HTTPS (o localhost) abre el video en vivo de Odoo; por
        HTTP, como al entrar desde el teléfono por la IP local, saca una foto
        y lee el código de la imagen (BarcodeDetector del navegador o la
        librería ZXing que trae Odoo). También acepta tipear el código o una
        pistola lectora USB.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web", "stock"],
    "data": [
        "views/barcode_lookup_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "stock_barcode_lookup/static/src/js/barcode_lookup_app.js",
            "stock_barcode_lookup/static/src/xml/barcode_lookup_app.xml",
            "stock_barcode_lookup/static/src/scss/barcode_lookup_app.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
