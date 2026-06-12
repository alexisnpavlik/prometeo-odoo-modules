from odoo import models
import logging

_logger = logging.getLogger(__name__)

class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_pos_payment_method(self):
        res = super()._loader_params_payment_method()
        res['search_params']['fields'].append('card_id')
        _logger.info("card_installment: loader_params_payment_method fields -> %s", res.get('search_params', {}).get('fields'))
            
        return res
