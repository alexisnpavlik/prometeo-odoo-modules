import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_assign(self, force_qty=False):
        res = super()._action_assign(force_qty=force_qty)
        outgoing = self.filtered(
            lambda m: m.picking_type_id.code == "outgoing"
            and m.state not in ("done", "cancel")
        )
        for move in outgoing:
            if move.quantity != move.product_uom_qty:
                move.quantity = move.product_uom_qty
                _logger.info(
                    "stock_picking_auto_qty: forzada qty=%s en move %s (picking %s)",
                    move.product_uom_qty,
                    move.id,
                    move.picking_id.name or move.id,
                )
        return res
