import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    mp_account_id = fields.Many2one(
        "mercadopago.account", string="Cuenta de Mercado Pago",
        help="Varias cajas pueden apuntar a la misma cuenta con QR distintos.",
    )
    mp_pos_id = fields.Char(
        string="ID del QR (caja)",
        help="pos_id del QR de esta caja. Separa la bandeja de las demás cajas.",
    )
    accept_alias_payments = fields.Boolean(
        string="Aceptar cobros por alias",
        help="Los cobros por alias no traen caja ni pagador identificable.",
    )
    auto_impute_single_match = fields.Boolean(
        string="Imputar solo cuando hay un único candidato",
        help="Desactivado, el cajero confirma siempre.",
    )
    search_window_minutes = fields.Integer(default=5, required=True)
    poll_interval_seconds = fields.Integer(default=10, required=True)
    amount_tolerance = fields.Float(
        default=0.0,
        help="0 significa sólo coincidencia exacta de monto.",
    )
    require_manager_for_manual = fields.Boolean(
        string="Exigir encargado para aprobación manual",
    )

    def _get_payment_terminal_selection(self):
        """Agrega el validador de Mercado Pago al selector de terminal."""
        return super()._get_payment_terminal_selection() + [
            ("mercadopago_validator", "Mercado Pago - Validador de QR")
        ]

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Campos que el POS sincroniza al navegador.

        Whitelist explícita: ninguna credencial entra acá. Ver RNF-002.
        """
        return super()._load_pos_data_fields(config_id) + [
            "mp_pos_id", "accept_alias_payments", "auto_impute_single_match",
            "search_window_minutes", "poll_interval_seconds", "amount_tolerance",
            "require_manager_for_manual",
        ]

    def _check_pos_access(self):
        """Verifica que quien llama por RPC sea un usuario del POS."""
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("No tenés acceso a la bandeja de Mercado Pago."))
