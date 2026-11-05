# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    cca_is_checking_account = fields.Boolean(
        string="Cuenta corriente (cca)",
        help="Los pedidos pagados con este método se registran como retiro a cuenta del cliente.",
    )

    @api.constrains("cca_is_checking_account", "journal_id", "split_transactions")
    def _check_cca_is_checking_account(self):
        """El método de cuenta corriente no mueve plata: sin diario y con pagos divididos."""
        for method in self.filtered("cca_is_checking_account"):
            if method.journal_id or not method.split_transactions:
                raise ValidationError(_(
                    "El método de pago %s es de cuenta corriente: debe tener 'Identificar cliente' "
                    "(pagos divididos) activado y no tener diario.", method.name
                ))

    @api.constrains("cca_is_checking_account")
    def _check_cca_single_per_config(self):
        """Revalida las cajas del método: no puede haber dos de cuenta corriente."""
        self.filtered("cca_is_checking_account").config_ids._check_single_cca_payment_method()

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Agrega al POS la marca de cuenta corriente."""
        return super()._load_pos_data_fields(config_id) + ["cca_is_checking_account"]
