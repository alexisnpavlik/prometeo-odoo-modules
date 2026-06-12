{
    "name": "Card installment",
    "author": "ADHOC SA",
    "website": "https://www.adhoc.com.ar",
    "category": "Technical",
    "version": "18.0.1.1.0",
    "depends": ["product", "account", "point_of_sale"],
    "license": "LGPL-3",
    "images": [],
    "installable": True,
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/account_card.xml",
        "data/decimal_installment_coeficent.xml",
        "views/account_card.xml",
        "views/card_installment_view.xml",
        "views/pos_payment_method_view.xml"
    ],
    "demo": [
        "demo/product_product.xml",
        "demo/account_card.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "card_installment/static/src/js/*.js",
            "card_installment/static/src/overrides/components/popup.js",
            "card_installment/static/src/overrides/components/popup.xml",
            "card_installment/static/src/css/*.css",
            "card_installment/static/src/xml/*.xml",
        ],
    },
}
