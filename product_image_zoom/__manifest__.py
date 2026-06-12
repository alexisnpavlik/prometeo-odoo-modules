{
    "name": "Product Image Zoom",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Ampliar imagen del producto al hacer clic en la ficha",
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "depends": ["product", "web"],
    "data": ["views/product_views.xml"],
    "assets": {
        "web.assets_backend": [
            "product_image_zoom/static/src/image_zoom_field.scss",
            "product_image_zoom/static/src/image_zoom_field.xml",
            "product_image_zoom/static/src/image_zoom_field.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
    "license": "LGPL-3",
}
