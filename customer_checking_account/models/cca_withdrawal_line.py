# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CcaWithdrawalLine(models.Model):
    _name = "cca.withdrawal.line"
    _description = "Línea de retiro de cliente"
    _order = "withdrawal_id, sequence, id"

    withdrawal_id = fields.Many2one(
        comodel_name="cca.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="withdrawal_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto",
        required=True,
        domain="[('sale_ok', '=', True)]",
    )
    name = fields.Char(string="Descripción")
    quantity = fields.Float(string="Cantidad", default=1.0, digits="Product Unit of Measure")
    price_unit = fields.Float(
        string="Precio unitario",
        digits="Product Price",
        compute="_compute_price_unit",
        store=True,
        readonly=False,
        precompute=True,
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_price_subtotal",
        store=True,
        currency_field="currency_id",
    )

    @api.depends("product_id")
    def _compute_price_unit(self):
        """Precio de venta del producto (list_price). Editable mientras el retiro esté en borrador."""
        for line in self:
            line.price_unit = line.product_id.list_price if line.product_id else 0.0

    @api.depends("quantity", "price_unit")
    def _compute_price_subtotal(self):
        """Subtotal sin recargo: cantidad por precio."""
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Propone la descripción del producto."""
        if self.product_id:
            self.name = self.product_id.display_name

    def action_open_product(self):
        """Abre la ficha del producto de la línea."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.product_id.display_name,
            "res_model": "product.product",
            "res_id": self.product_id.id,
            "view_mode": "form",
        }

    @api.constrains("quantity", "price_unit")
    def _check_values(self):
        """Cantidad positiva y precio no negativo."""
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("La cantidad debe ser mayor a cero."))
            if line.price_unit < 0:
                raise ValidationError(_("El precio no puede ser negativo."))
