from odoo import fields, models


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
