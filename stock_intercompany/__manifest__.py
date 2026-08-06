# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

{
    "name": "Stock Intercompany Delivery-Reception",
    "Summary": "Module that adds possibility for intercompany Delivery-Reception",
    "version": "18.0.2.0.0",
    "author": "Camptocamp, Alexis Medina, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/multi-company",
    "category": "Warehouse Management",
    "depends": ["stock"],
    "installable": True,
    "license": "AGPL-3",
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/res_config_settings.xml",
        "views/stock_picking_views.xml",
    ],
}
