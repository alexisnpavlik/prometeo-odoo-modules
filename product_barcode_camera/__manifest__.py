{
    "name": "Producto - Código de barras con cámara",
    "version": "18.0.1.0.2",
    "category": "Hidden/Tools",
    "summary": "El campo código de barras del producto suma un botón que escanea con la cámara",
    "description": """
        En la ficha del producto (plantilla y variante), el campo Código de
        barras muestra en el celular un botón de cámara. Al tocarlo se abre el
        escáner de Odoo y el código leído se carga en el campo.

        También aparece en PC y tablet (con webcam); se puede seguir tipeando
        o usando el lector láser.

        El escáner usa getUserMedia: el navegador solo da la cámara por HTTPS
        (o localhost). Entrando por IP local sin HTTPS el botón no aparece.
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["product", "web"],
    "data": [
        "views/product_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "product_barcode_camera/static/src/js/barcode_camera_field.js",
            "product_barcode_camera/static/src/xml/barcode_camera_field.xml",
            "product_barcode_camera/static/src/scss/barcode_camera_field.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
