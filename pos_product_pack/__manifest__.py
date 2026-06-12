# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "POS Product Pack",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Integrate OCA product pack into the Point of Sale",
    "author": "Alexis Medina",
    "license": "AGPL-3",
    "depends": ["point_of_sale", "product_pack"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_product_pack/static/src/js/pos_store.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
