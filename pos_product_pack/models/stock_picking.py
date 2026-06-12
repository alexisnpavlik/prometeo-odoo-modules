# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, models
from odoo.tools import float_is_zero


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _create_move_from_pos_order_lines(self, lines):
        """Skip stock moves for packs themselves and instead create moves for their components
        if the pack type is non_detailed."""
        self.ensure_one()

        normal_lines = self.env["pos.order.line"]
        pack_lines = []

        for line in lines:
            if line.product_id.pack_ok:
                if line.product_id.pack_type == "non_detailed":
                    pack_lines.append(line)
            else:
                normal_lines |= line

        # Handle normal lines using original logic
        if normal_lines:
            super()._create_move_from_pos_order_lines(normal_lines)

        # Handle non_detailed pack lines by creating moves for their components
        if pack_lines:
            move_vals = []
            for line in pack_lines:
                for pack_line in line.product_id.pack_line_ids:
                    comp_product = pack_line.product_id
                    # Only create stock moves for consumable/storable products
                    if comp_product.type == "consu":
                        qty = abs(line.qty * pack_line.quantity)
                        if not float_is_zero(
                            qty, precision_rounding=comp_product.uom_id.rounding
                        ):
                            move_vals.append(
                                {
                                    "name": f"{line.name} - {comp_product.name}",
                                    "product_uom": comp_product.uom_id.id,
                                    "picking_id": self.id,
                                    "picking_type_id": self.picking_type_id.id,
                                    "product_id": comp_product.id,
                                    "product_uom_qty": qty,
                                    "location_id": self.location_id.id,
                                    "location_dest_id": self.location_dest_id.id,
                                    "company_id": self.company_id.id,
                                }
                            )
            if move_vals:
                moves = self.env["stock.move"].create(move_vals)
                confirmed_moves = moves._action_confirm()
                # Odoo's _add_mls_related_to_order will handle moves whose product_id is not in lines
                confirmed_moves._add_mls_related_to_order(lines, are_qties_done=True)
                confirmed_moves.picked = True
