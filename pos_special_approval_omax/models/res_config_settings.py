# -*- coding: utf-8 -*-

import secrets

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Credenciales de la caja: nunca viajan al frontend del POS.
APPROVAL_SECRET_FIELDS = ('approval_pin', 'approval_barcode')


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
        help='Una vez autorizado el pedido, no vuelve a pedir autorización en ese pedido'
    )

    # Validation type selection
    validation_type = fields.Selection([
        ('all', 'PIN y código de barras'),
        ('pin', 'Solo PIN'),
        ('barcode', 'Solo código de barras'),
    ], string='Validation Type',
       default='all')

    # Credenciales de autorización de la caja (compartidas por quien autoriza)
    approval_pin = fields.Char(
        string='PIN de autorización',
        size=10,
        copy=False,
        help='PIN numérico que autoriza las operaciones en esta caja.'
    )
    approval_barcode = fields.Char(
        string='Código de barras de autorización',
        copy=False,
        help='Código de barras (tarjeta/credencial) que autoriza las operaciones en esta caja.'
    )
    has_approval_pin = fields.Boolean(compute='_compute_has_approval_credentials', store=True)
    has_approval_barcode = fields.Boolean(compute='_compute_has_approval_credentials', store=True)

    # Barcode validation hardening
    enforce_barcode_scanner = fields.Boolean(
        string='Barcode Scanner Only',
        default=False,
        help='In the barcode validation popup, block manual typing and pasting; '
             'only accept input from a physical barcode scanner (detected by '
             'keystroke timing). Disable to allow manual entry.'
    )

    # Usuarios a los que NO se les pide autorización (el resto, sí)
    excluded_user_ids = fields.Many2many(
        'res.users',
        'pos_approval_excluded_user_rel',
        'config_id',
        'user_id',
        string='Usuarios excluidos de autorización',
        domain=[('share', '=', False)],
        help='A estos usuarios no se les pide autorización. A todos los demás, sí.'
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

    @api.depends('approval_pin', 'approval_barcode')
    def _compute_has_approval_credentials(self):
        """Indica al POS qué credenciales tiene la caja sin exponer su valor."""
        for config in self:
            config.has_approval_pin = bool(config.approval_pin)
            config.has_approval_barcode = bool(config.approval_barcode)

    @api.constrains('approval_pin')
    def _check_approval_pin(self):
        """El PIN de la caja debe ser numérico."""
        for config in self:
            if config.approval_pin and not config.approval_pin.isdigit():
                raise ValidationError(_('El PIN de autorización debe contener solo números.'))

    def _load_pos_data(self, data):
        """Quita las credenciales de la caja de lo que se envía al POS."""
        res = super()._load_pos_data(data)
        for record in res.get('data', []):
            for field_name in APPROVAL_SECRET_FIELDS:
                record.pop(field_name, None)
        if res.get('fields'):
            res['fields'] = [f for f in res['fields'] if f not in APPROVAL_SECRET_FIELDS]
        return res

    def action_generate_approval_pin(self):
        """Genera un PIN nuevo de 6 dígitos (rotación tras una filtración)."""
        for config in self:
            config.approval_pin = ''.join(secrets.choice('0123456789') for _i in range(6))
        return True


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    validate_add_product_to_order = fields.Boolean(related='pos_config_id.validate_add_product_to_order', readonly=False)
    manager_validation = fields.Boolean(related='pos_config_id.manager_validation', readonly=False)
    one_time_password = fields.Boolean(related='pos_config_id.one_time_password', readonly=False)
    validation_type = fields.Selection(related='pos_config_id.validation_type', readonly=False)
    approval_pin = fields.Char(related='pos_config_id.approval_pin', readonly=False)
    approval_barcode = fields.Char(related='pos_config_id.approval_barcode', readonly=False)
    enforce_barcode_scanner = fields.Boolean(related='pos_config_id.enforce_barcode_scanner', readonly=False)
    excluded_user_ids = fields.Many2many(related='pos_config_id.excluded_user_ids', readonly=False)
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

    def action_generate_approval_pin(self):
        """Genera un PIN nuevo para la caja que se está configurando."""
        self.pos_config_id.action_generate_approval_pin()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
