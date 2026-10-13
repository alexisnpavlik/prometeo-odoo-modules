# -*- coding: utf-8 -*-

from odoo import _, models


class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    def action_create_returns(self):
        """Desde el botón Devolver de la compra: valida la devolución en el acto."""
        if not self.env.context.get("simplify_auto_return"):
            return super().action_create_returns()
        self.ensure_one()
        return_picking = self._create_return()
        tracked = return_picking.move_ids.filtered(lambda m: m.product_id.tracking != "none")
        if not tracked:
            # sudo acotado: el usuario del kiosco no tiene por qué validar en Inventario.
            picking = return_picking.sudo()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.with_context(skip_sms=True, skip_backorder=True).button_validate()
        if return_picking.state == "done":
            title, kind = _("Devolución registrada"), "success"
            message = _("Mercadería devuelta al proveedor (%s).", return_picking.name)
        else:
            title, kind = _("Devolución pendiente"), "warning"
            message = _("Se creó la devolución %s; tiene productos con lote o número de serie "
                        "y hay que validarla cargándolo.", return_picking.name)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": kind,
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
