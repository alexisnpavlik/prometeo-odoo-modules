from odoo import models, fields


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    card_id = fields.Many2one(
        "account.card",
        string='Credit Card',
        help='Credit card associated with this POS payment method'
    )

    def _load_pos_data_fields(self, config_id):
        data = super()._load_pos_data_fields(config_id)
        data.extend(['card_id'])
        return data

    def _get_pos_ui_payment_methods(self, params):
        result = super()._get_pos_ui_payment_methods(params)
        for item in result:
            rec = self.browse(item["id"])
            item["card_id"] = rec.card_id.id if rec.card_id else False
        return result
