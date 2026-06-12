# -*- coding: utf-8 -*-
{
    "name": "POS Global Discount on Main Screen",
    "version": "18.0.1.0.0",
    "category": "Sales/Point Of Sale",
    "summary": "Move Global Discount button to main POS screen, replacing the Internal Note button.",
    "description": """
        Moves the Global Discount button from the action popup/dialog to the main POS screen,
        replacing the Internal Notes button. The Internal Notes button is moved to the
        actions popup, and the redundant Discount button is removed from the popup.
    """,
    "author": "Alexis",
    "depends": ["point_of_sale", "pos_discount"],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_global_discount_button/static/src/js/control_buttons_patch.js",
            "pos_global_discount_button/static/src/xml/control_buttons.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
