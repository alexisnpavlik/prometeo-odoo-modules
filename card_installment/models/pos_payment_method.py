from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)

class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    card_id = fields.Many2one(
        "account.card",
        string='Credit Card',
        help='Credit card associated with this POS payment method'
    )

    def _load_pos_data_fields(self, config_id):
        data = super(PosPaymentMethod, self)._load_pos_data_fields(config_id)
        data.extend(['card_id'])
        _logger.warning("✅ Loader fields enviados: %s", data)
        return data
    
    def _get_pos_ui_payment_methods(self, params):
        result = super()._get_pos_ui_payment_methods(params)
        
        for item in result:
            rec = self.browse(item["id"])
            
            # --- Pasa aquí la verificación clave ---
            card_id = rec.card_id.id if rec.card_id else False
            item["card_id"] = card_id
            
            _logger.warning("✅ Método ID %s tiene card_id: %s", item["id"], card_id) # ¡Añade este log de verificación!
            # ---------------------------------------

        _logger.warning("✅ Valores enviados al POS: %s", result)
        return result