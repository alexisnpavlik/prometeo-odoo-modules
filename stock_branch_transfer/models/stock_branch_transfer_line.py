from odoo import api, fields, models


class StockBranchTransferLine(models.Model):
    _name = "stock.branch.transfer.line"
    _description = "Línea de traslado entre sucursales"

    transfer_id = fields.Many2one(
        "stock.branch.transfer", string="Traslado", required=True, ondelete="cascade", index=True
    )
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        domain=[("company_id", "=", False), ("type", "=", "consu"), ("is_storable", "=", True)],
    )
    uom_id = fields.Many2one(related="product_id.uom_id", string="Unidad")
    qty_sent = fields.Float(string="Enviado", digits="Product Unit of Measure")
    qty_received = fields.Float(string="Recibido", digits="Product Unit of Measure")

    @api.model_create_multi
    def create(self, vals_list):
        """Una línea nueva en un traslado ya enviado la agrega un manager y mueve stock."""
        lines = super().create(vals_list)
        lines.transfer_id._after_line_change(self.env.context)
        return lines

    def write(self, vals):
        """Cambiar cantidades o producto de un traslado ya enviado corrige el stock."""
        res = super().write(vals)
        if {"product_id", "qty_sent", "qty_received"} & set(vals):
            self.transfer_id._after_line_change(self.env.context)
        return res

    def unlink(self):
        """Quitar una línea de un traslado ya enviado devuelve su stock."""
        transfers = self.transfer_id
        transfers._before_line_change(self.env.context)
        res = super().unlink()
        transfers._after_line_change(self.env.context, checked=True)
        return res
