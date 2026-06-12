# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    # POS validation fields
    pos_barcode = fields.Char(
        string='POS Barcode',
        help='Barcode for POS manager validation'
    )
    
    pos_password = fields.Char(
        string='POS Password',
        help='Password for POS manager validation'
    )
    
    pos_pin = fields.Char(
        string='POS PIN',
        help='PIN for POS manager validation',
        size=10
    )
    
    @api.constrains('pos_pin')
    def _check_pos_pin(self):
        for user in self:
            if user.pos_pin and not user.pos_pin.isdigit():
                raise models.ValidationError('POS PIN must contain only numbers.')
    
    @api.model
    def validate_pos_credentials(self, user_id, barcode=None, password=None, pin=None):
        """Validate POS credentials for a user"""
        user = self.browse(user_id)
        if not user.exists():
            return False
            
        validation_methods = []
        
        if barcode and user.pos_barcode:
            validation_methods.append(user.pos_barcode == barcode)
            
        if password and user.pos_password:
            validation_methods.append(user.pos_password == password)
            
        if pin and user.pos_pin:
            validation_methods.append(user.pos_pin == pin)
            
        # Return True if at least one validation method passes
        return any(validation_methods) if validation_methods else False