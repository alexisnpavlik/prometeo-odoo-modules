# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .simplify_options import active_view_options, hide_option_nodes, is_option_active


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    simplify_confirm_receive = fields.Boolean(
        string="Confirmar e ingresar en un paso",
        compute="_compute_simplify_confirm_receive",
    )
    # El botón Imprimir propio reemplaza a los de Odoo cuando esos se ocultan.
    simplify_print = fields.Boolean(compute="_compute_simplify_confirm_receive")
    simplify_can_return = fields.Boolean(compute="_compute_simplify_can_return")

    @api.depends("picking_ids.state")
    @api.depends_context("uid")
    def _compute_simplify_can_return(self):
        """Hay mercadería recibida para devolver y el botón Devolver está activado."""
        enabled = is_option_active(self.env, "purchase_return_button")
        for order in self:
            order.simplify_can_return = enabled and bool(order._simplify_done_receipts())

    def _simplify_done_receipts(self):
        """Recepciones validadas de la orden (las devoluciones salen de acá)."""
        return self.picking_ids.filtered(
            lambda p: p.state == "done" and p.picking_type_code == "incoming"
        )

    def action_simplify_return(self):
        """Devolver: abre el asistente de devolución sobre la última recepción.
        Con el contexto simplify_auto_return, la devolución se valida al confirmar."""
        self.ensure_one()
        receipt = self._simplify_done_receipts().sorted("date_done")[-1:]
        if not receipt:
            raise UserError(_("Esta compra todavía no tiene mercadería recibida para devolver."))
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.act_stock_return_picking")
        action["name"] = _("Devolver al proveedor")
        action["context"] = {
            "active_id": receipt.id,
            "active_ids": receipt.ids,
            "active_model": "stock.picking",
            "simplify_auto_return": True,
        }
        return action

    @api.depends("state")
    @api.depends_context("uid")
    def _compute_simplify_confirm_receive(self):
        """Refleja las opciones de Ajustes que muestran botones propios."""
        confirm = is_option_active(self.env, "purchase_confirm_receive")
        show_print = is_option_active(self.env, "hide_purchase_order_send_print")
        for order in self:
            order.simplify_confirm_receive = confirm
            order.simplify_print = show_print

    def _simplify_receive_now(self):
        """Valida las recepciones pendientes por la cantidad pedida.

        Devuelve False si alguna quedó pendiente (productos con lote o número
        de serie, que necesitan cargarlo a mano). La validación corre con sudo:
        el usuario del kiosco no tiene por qué tener permisos de Inventario.
        """
        received = True
        for picking in self.sudo().picking_ids.filtered(lambda p: p.state not in ("done", "cancel")):
            if picking.move_ids.filtered(lambda m: m.product_id.tracking != "none"):
                received = False
                continue
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.with_context(skip_sms=True, skip_backorder=True).button_validate()
            received = received and picking.state == "done"
        return received

    def _simplify_receive_notification(self, received, next_action):
        """Aviso de resultado de Confirmar e ingresar / Reabastecer."""
        self.ensure_one()
        if received:
            title, kind = _("Mercadería ingresada"), "success"
            message = _("Compra %s confirmada y mercadería ingresada al stock.", self.name)
        else:
            title, kind = _("Compra confirmada"), "warning"
            message = _("Compra %s confirmada. Hay productos con lote o número de serie: "
                        "la recepción quedó pendiente para cargarlo (botón Recibir productos).", self.name)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": title, "message": message, "type": kind, "sticky": False, "next": next_action},
        }

    def action_simplify_confirm_receive(self):
        """Confirmar e ingresar: confirma la compra y valida la recepción en un paso."""
        self.ensure_one()
        if self.state in ("draft", "sent"):
            self.button_confirm()
        received = self._simplify_receive_now()
        return self._simplify_receive_notification(received, {"type": "ir.actions.client", "tag": "soft_reload"})

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        """Oculta los elementos de las opciones activadas en Ajustes."""
        arch, view = super()._get_view(view_id, view_type, **options)
        hide_option_nodes(self.env, arch, view_type, self._name)
        return arch, view

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type="form", **options):
        """Separa la caché de vistas según qué opciones de vistas están activadas."""
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + active_view_options(self.env, self._name)
