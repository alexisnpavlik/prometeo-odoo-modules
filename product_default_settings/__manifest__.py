{
    "name": "Product Default Settings",
    "version": "18.0.2.0.0",
    "category": "Inventory/Inventory",
    "summary": "Valores por defecto y pestañas visibles en la ficha de producto.",
    "author": "Alexis Medina",
    "website": "alexis.medn@gmail.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "sale", "purchase", "stock"],
    "data": [
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
