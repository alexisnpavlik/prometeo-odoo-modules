# -*- coding: utf-8 -*-

from odoo import models, fields


class PosConfig(models.Model):
    _inherit = 'pos.config'

    # Main validation field
    manager_validation = fields.Boolean(
        string='POS Manager Validation',
        help='Enable manager validation for POS operations'
    )

    # One time password setting
    one_time_password = fields.Boolean(
        string='One Time Password for Order',
        help='Enter password once per order and reuse for that person'
    )

    # Validation type selection
    validation_type = fields.Selection([
        ('all', 'All'),
        ('barcode', 'Only Barcode'),
        ('password', 'Only Password'),
        ('pin', 'Only PIN'),
        ('pin_password', 'PIN and Password'),
        ('pin_barcode', 'PIN and Barcode'),
        ('password_barcode', 'Password and Barcode')
    ], string='Validation Type',
       default='all')

    # Virtual keyboard for password
    virtual_keyboard = fields.Boolean(
        string='Virtual Keyboard for Password',
        help='Show virtual keyboard when password input is required'
    )

    # Manager selection
    manager_ids = fields.Many2many(
        'res.users',
        'manager_validation_rel',
        'config_id',
        'user_id',
        string='POS Managers',
        domain=[('share', '=', False)],
        help='Users who can provide manager validation'
    )

    # Boolean fields for validation triggers
    validate_add_product_to_order = fields.Boolean(string='Add Product To Order')
    validate_order_line_deletion = fields.Boolean(string='Order Line Deletion')
    validate_order_deletion = fields.Boolean(string='Order Deletion')
    validate_apply_discount = fields.Boolean(string='Apply Discount')
    validate_price_change = fields.Boolean(string='Price Change')
    validate_quantity_change = fields.Boolean(string='Quantity Change')
    validate_payment = fields.Boolean(string='Payment')
    validate_refund = fields.Boolean(string='Refund')
    validate_payment_methods = fields.Boolean(string='Validate Payment Methods')
    validate_global_discount = fields.Boolean(string='Global Discount')

    validated_payment_method_ids = fields.Many2many(
        'pos.payment.method',
        'validated_payment_method_rel',
        'config_id',
        'payment_method_id',
        string='Payment Methods Requiring Validation'
    )

    validate_cash_move = fields.Boolean(string='Cash Move (Cash In/Out)')
    validate_open_session = fields.Boolean(string='Open Session')
    validate_close_session = fields.Boolean(string='Close Session')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    validate_add_product_to_order = fields.Boolean(related='pos_config_id.validate_add_product_to_order', readonly=False)
    manager_validation = fields.Boolean(related='pos_config_id.manager_validation', readonly=False)
    one_time_password = fields.Boolean(related='pos_config_id.one_time_password', readonly=False)
    validation_type = fields.Selection(related='pos_config_id.validation_type', readonly=False)
    virtual_keyboard = fields.Boolean(related='pos_config_id.virtual_keyboard', readonly=False)
    manager_ids = fields.Many2many(related='pos_config_id.manager_ids', readonly=False)
    validate_order_line_deletion = fields.Boolean(related='pos_config_id.validate_order_line_deletion', readonly=False)
    validate_order_deletion = fields.Boolean(related='pos_config_id.validate_order_deletion', readonly=False)
    validate_apply_discount = fields.Boolean(related='pos_config_id.validate_apply_discount', readonly=False)
    validate_price_change = fields.Boolean(related='pos_config_id.validate_price_change', readonly=False)
    validate_quantity_change = fields.Boolean(related='pos_config_id.validate_quantity_change', readonly=False)
    validate_payment = fields.Boolean(related='pos_config_id.validate_payment', readonly=False)
    validate_refund = fields.Boolean(related='pos_config_id.validate_refund', readonly=False)
    validate_payment_methods = fields.Boolean(related='pos_config_id.validate_payment_methods', readonly=False)
    validated_payment_method_ids = fields.Many2many(related='pos_config_id.validated_payment_method_ids', readonly=False)
    validate_cash_move = fields.Boolean(related='pos_config_id.validate_cash_move', readonly=False)
    validate_global_discount = fields.Boolean(related='pos_config_id.validate_global_discount', readonly=False)
    validate_open_session = fields.Boolean(related='pos_config_id.validate_open_session', readonly=False)
    validate_close_session = fields.Boolean(related='pos_config_id.validate_close_session', readonly=False)
