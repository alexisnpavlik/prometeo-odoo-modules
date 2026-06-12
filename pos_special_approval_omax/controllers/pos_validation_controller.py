# -*- coding: utf-8 -*-

import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PosValidationController(http.Controller):

    @http.route('/pos/validate_manager_credentials', type='json', auth='user', methods=['POST'])
    def validate_manager_credentials(self, manager_ids, credentials):
        """
        Validate manager credentials for POS operations
        
        :param manager_ids: List of manager user IDs
        :param credentials: Dict containing validation data (barcode, password, pin)
        :return: Dict with success status and user info
        """
        try:
            if not manager_ids:
                return {
                    'success': False,
                    'message': 'No managers configured for validation.'
                }

            # Get manager users
            managers = request.env['res.users'].sudo().browse(manager_ids)
            if not managers:
                return {
                    'success': False,
                    'message': 'Invalid manager configuration.'
                }

            # Extract credentials
            barcode = credentials.get('barcode', '').strip()
            password = credentials.get('password', '').strip()
            pin = credentials.get('pin', '').strip()

            # Validate against each manager
            for manager in managers:
                validation_passed = False
                
                # Check barcode validation
                if barcode and manager.pos_barcode:
                    if manager.pos_barcode == barcode:
                        validation_passed = True
                        
                # Check password validation
                if password and manager.pos_password:
                    if manager.pos_password == password:
                        validation_passed = True
                        
                # Check PIN validation
                if pin and manager.pos_pin:
                    if manager.pos_pin == pin:
                        validation_passed = True

                if validation_passed:
                    return {
                        'success': True,
                        'user_id': manager.id,
                        'user_name': manager.name,
                        'message': 'Validation successful.'
                    }

            # No validation passed
            return {
                'success': False,
                'message': 'Invalid credentials. Please check your barcode, password, or PIN and try again.'
            }

        except Exception as e:
            _logger.error("Error in POS manager validation: %s", str(e))
            return {
                'success': False,
                'message': 'An error occurred during validation. Please try again.'
            }