# -*- coding: utf-8 -*-

import hmac
import logging

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _matches(expected, given):
    """Compara credenciales en tiempo constante; vacío nunca coincide."""
    return bool(expected) and bool(given) and hmac.compare_digest(expected.encode(), given.encode())


class PosValidationController(http.Controller):

    @http.route('/pos/validate_approval', type='json', auth='user', methods=['POST'])
    def validate_approval(self, config_id, credentials, operation=None, order_reference=None, session_id=None):
        """
        Valida la credencial de autorización contra la caja (pos.config) y registra el intento.

        :param config_id: id de la caja del POS abierto
        :param credentials: dict con 'pin' o 'barcode'
        :param operation: clave de la operación que se autoriza (refund, price_change, ...)
        :param order_reference: referencia del pedido en curso, si hay
        :param session_id: id de la sesión abierta, si hay
        :return: dict con success y message
        """
        try:
            config = request.env['pos.config'].browse(int(config_id))
            config.check_access('read')
            config = config.sudo()
            log_model = request.env['pos.approval.log'].sudo()

            if log_model._is_config_locked(config):
                return {
                    'success': False,
                    'message': _('Demasiados intentos fallidos. Esperá unos minutos y volvé a intentar.'),
                }

            pin = (credentials.get('pin') or '').strip()
            barcode = (credentials.get('barcode') or '').strip()
            method = 'pin' if pin else 'barcode' if barcode else False
            success = _matches(config.approval_pin, pin) or _matches(config.approval_barcode, barcode)

            session = request.env['pos.session'].sudo().browse(int(session_id)) if session_id else False
            log_model.create({
                'config_id': config.id,
                'session_id': session.id if session and session.exists() else False,
                'user_id': request.env.uid,
                'operation': operation,
                'order_reference': order_reference,
                'method': method,
                'success': success,
            })

            if success:
                return {'success': True, 'message': _('Autorización correcta.')}
            return {'success': False, 'message': _('Credencial incorrecta.')}

        except (AccessError, MissingError):
            return {'success': False, 'message': _('No tenés acceso a esta caja.')}
        except Exception as e:
            _logger.error("Error validando autorización del POS: %s", str(e))
            return {'success': False, 'message': _('Ocurrió un error al validar. Intentá de nuevo.')}
