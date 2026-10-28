from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    branch_transfer_id = fields.Many2one(
        "stock.branch.transfer", string="Traslado", index=True, copy=False
    )
