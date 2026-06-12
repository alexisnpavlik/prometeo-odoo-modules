# -*- coding: utf-8 -*-
{
    'name': 'POS Manager Special Approval',
    'version': '18.0.1.0',
    'category': 'Point of Sale',
    'sequence': 1,
    'author': 'OMAX Informatics',
    'website': 'https://omaxinformatics.com/',
    'description': '''
        POS Manager Validation System with Multiple Authentication Methods
    ''',
    'depends': ['point_of_sale','pos_discount'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/res_users_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_special_approval_omax/static/src/js/**/*',
            'pos_special_approval_omax/static/src/xml/**/*',
            'pos_special_approval_omax/static/src/css/**/*',
        ],
    },
    'demo': [],
    'test': [],
    'images': ['static/description/banner.png'],
    'license': 'OPL-1',
    'currency': 'USD',
    'price': 30.00,
    'installable': True,
    'auto_install': False,
    'application': True,
    'pre_init_hook': 'pre_init_check',
    'module_type': 'official',
    'summary': '''
        This module adds validation system for POS operations including:
        1. Multi-Authentication Methods
        - Barcode Scan
        - Password
        - PIN Code
        - Virtual keyboard support for password entry

        2. One-Time Password per Order Feature
        - Authenticate once per order and skip repeated validation for the same manager on that order.

        3. Configurable Validation Triggers
        Enable manager validation for:
        - Order deletion
        - Applying discounts
        - Changing product prices
        - Processing payments
        - Processing refunds
        - Cash in / Cash out operations
        - Deleting order lines
        - Changing product quantities
        - Adding products to an order
        - Validations on selected payment methods only

        4. Flexible Configuration in POS Settings
        - Enable/disable the entire POS Manager Validation feature.
        - Choose validation type (All, Only Barcode, Only Password, Only PIN, Combinations).
        - Select managers (Internal Users) who are authorized for validation.
        - Optional "Virtual Keyboard" for password entry.
        - Select specific payment methods that require validation.

        5. Interactive POS Popups
        - Selection popup: choose between Barcode, Password, or PIN
        - Barcode scan popup (with camera scan functionality)
        - Password entry popup (with optional virtual keyboard)
        - PIN entry popup
        - Wrong credentials popup

        POS Manager Special Approval adds secure manager validation in Odoo POS with PIN, password, or barcode authentication. Control discounts, price changes, refunds, payments, order edits, and cash operations with configurable approval triggers.
        POS manager approval POS special approval POS validation POS manager PIN POS barcode approval POS password approval POS one-time password POS OTP per order POS order validation POS discount approval POS price change approval POS refund approval POS payment approval POS cashier control POS cash in/out approval POS secure operations POS restricted access POS supervisor approval Odoo POS security Odoo POS manager validation Point Of Sale Manager Validation Set validation method Validate price changes Validate Cash movements Quantity validations Validate Payments Validate Refunds Discount validations Set one time password Validate Payment methods Validate Order & Order line deletion
    '''
}
