from odoo import api, fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    allow_cash_in_out = fields.Boolean(
        string="Permitir ingresos/retiros",
        help="Permite usar este método en el popup de Ingreso/Retiro del POS. "
        "El movimiento se registra en el diario del método.",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ["allow_cash_in_out"]
