import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_assign(self):
        res = super().action_assign()
        outgoing = self.filtered(lambda p: p.picking_type_code == "outgoing")
        for picking in outgoing:
            for move in picking.move_ids:
                if move.state in ("done", "cancel"):
                    continue
                if move.quantity != move.product_uom_qty:
                    move.quantity = move.product_uom_qty
                    _logger.info(
                        "stock_picking_auto_qty: forzada qty=%s en move %s (picking %s)",
                        move.product_uom_qty,
                        move.id,
                        picking.name,
                    )
        return res
