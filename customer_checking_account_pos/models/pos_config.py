# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PosConfig(models.Model):
    _inherit = "pos.config"

    cca_payment_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto de pago de cuenta corriente",
        compute="_compute_cca_payment_product_id",
    )

    def _compute_cca_payment_product_id(self):
        """Producto que el cajero usa para cobrar cuotas desde el POS."""
        product = self.env.ref(
            "customer_checking_account_pos.product_cca_pos_payment", raise_if_not_found=False
        )
        for config in self:
            config.cca_payment_product_id = product

    @api.constrains("payment_method_ids")
    def _check_single_cca_payment_method(self):
        """Una caja admite un solo método de pago de cuenta corriente."""
        for config in self:
            if len(config.payment_method_ids.filtered("cca_is_checking_account")) > 1:
                raise ValidationError(_(
                    "La caja %s tiene más de un método de pago de cuenta corriente.", config.name
                ))
