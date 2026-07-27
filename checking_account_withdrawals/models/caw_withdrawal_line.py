# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CawWithdrawalLine(models.Model):
    _name = "caw.withdrawal.line"
    _description = "Línea de retiro de cuenta corriente"
    _order = "withdrawal_id, sequence, id"

    withdrawal_id = fields.Many2one(
        comodel_name="caw.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        related="withdrawal_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto",
        required=True,
        ondelete="restrict",
    )
    name = fields.Char(string="Descripción")
    quantity = fields.Float(
        string="Cantidad",
        default=1.0,
        required=True,
        digits="Product Unit of Measure",
    )
    price_unit = fields.Float(
        string="Precio unitario",
        required=True,
        digits="Product Price",
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_price_subtotal",
        store=True,
        currency_field="currency_id",
    )

    @api.depends("quantity", "price_unit")
    def _compute_price_subtotal(self):
        """Subtotal de la línea, sin impuestos."""
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.constrains("quantity", "price_unit")
    def _check_positive_values(self):
        """Cantidad y precio no pueden ser negativos."""
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("La cantidad de la línea debe ser mayor a cero."))
            if line.price_unit < 0:
                raise ValidationError(_("El precio unitario no puede ser negativo."))

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Propone descripción y precio de lista del producto."""
        for line in self:
            if line.product_id:
                line.name = line.product_id.display_name
                line.price_unit = line.product_id.list_price
