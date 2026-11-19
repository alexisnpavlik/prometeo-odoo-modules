# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import api, fields, models

# Bloqueo anti fuerza bruta: intentos fallidos por caja dentro de la ventana.
MAX_FAILED_ATTEMPTS = 10
FAILED_WINDOW_MINUTES = 10


class PosApprovalLog(models.Model):
    _name = 'pos.approval.log'
    _description = 'Registro de autorizaciones del POS'
    _order = 'create_date desc, id desc'

    config_id = fields.Many2one('pos.config', string='Caja', required=True, index=True, ondelete='cascade')
    session_id = fields.Many2one('pos.session', string='Sesión', ondelete='set null')
    user_id = fields.Many2one('res.users', string='Usuario', required=True, ondelete='restrict')
    operation = fields.Char(string='Operación')
    order_reference = fields.Char(string='Pedido')
    method = fields.Selection([('pin', 'PIN'), ('barcode', 'Código de barras')], string='Método')
    success = fields.Boolean(string='Autorizada')

    @api.model
    def _is_config_locked(self, config):
        """True si la caja superó los intentos fallidos permitidos en la ventana reciente."""
        since = fields.Datetime.now() - timedelta(minutes=FAILED_WINDOW_MINUTES)
        failed = self.search_count([
            ('config_id', '=', config.id),
            ('success', '=', False),
            ('create_date', '>=', since),
        ])
        return failed >= MAX_FAILED_ATTEMPTS
