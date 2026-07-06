# -*- coding: utf-8 -*-
import os
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class SentryConfigController(http.Controller):

    @http.route('/prometeo_sentry_monitoring/config', type='http', auth='public', methods=['GET'], cors='*')
    def get_config(self):
        """
        Devuelve la configuración de Sentry al frontend, específicamente el DSN.
        Intenta leer de la variable de entorno SENTRY_DSN, luego de ir.config_parameter
        y finalmente usa el fallback hardcodeado.
        """
        try:
            # 1. Intentar variable de entorno SENTRY_DSN
            dsn = os.environ.get('SENTRY_DSN')
            
            # 2. Si no existe, intentar de ir.config_parameter
            if not dsn:
                # Usamos sudo() porque la ruta es auth='public' pero necesitamos acceder a ir.config_parameter
                dsn = request.env['ir.config_parameter'].sudo().get_param('prometeo_sentry_monitoring.sentry_dsn')
                
            # 3. Fallback final si ninguno está seteado
            if not dsn:
                dsn = "https://5e7994545829f0e490b60b785ac8d645@o4511665781276672.ingest.us.sentry.io/4511665789272064"
            
            payload = {
                'dsn': dsn.strip() if dsn else ""
            }
            
            return request.make_response(
                json.dumps(payload),
                headers=[
                    ('Content-Type', 'application/json'),
                    ('Cache-Control', 'no-cache, no-store, must-revalidate')
                ]
            )
        except Exception as e:
            _logger.error("Error al obtener la configuración de Sentry: %s", str(e))
            return request.make_response(
                json.dumps({'dsn': ''}),
                headers=[('Content-Type', 'application/json')]
            )
