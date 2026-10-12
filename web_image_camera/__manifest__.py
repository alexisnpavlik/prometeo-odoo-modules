{
    "name": "Web - Foto con cámara",
    "version": "18.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "En el teléfono, los campos de imagen suman un botón que abre la cámara",
    "description": """
        En celulares, cada campo de imagen editable (foto del producto, del
        contacto, etc.) muestra un botón de cámara junto al lápiz. El lápiz
        sigue abriendo la galería; la cámara abre directo la cámara trasera.

        Usa el atributo HTML capture="environment" del input de archivos: no
        pide permisos de cámara al navegador, así que funciona también sin
        HTTPS (por ejemplo, entrando por la IP local).
    """,
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "web_image_camera/static/src/js/file_uploader_capture.js",
            "web_image_camera/static/src/xml/image_camera.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
