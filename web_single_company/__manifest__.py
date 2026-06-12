{
    "name": "Web Single Company",
    "version": "18.0.1.0.0",
    "summary": "Fuerza selección de una única empresa activa por usuario",
    "category": "Web",
    "depends": ["web"],
    "assets": {
        "web.assets_web": [
            "web_single_company/static/src/company_selector_patch.js",
            "web_single_company/static/src/single_company.scss",
        ],
    },
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
