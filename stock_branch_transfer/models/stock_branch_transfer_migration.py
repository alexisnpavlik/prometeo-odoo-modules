import logging

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

from .stock_branch_transfer import INTERNAL

_logger = logging.getLogger(__name__)


class StockBranchTransfer(models.Model):
    _inherit = "stock.branch.transfer"

    @api.model
    def migrate_from_stock_intercompany(self):
        """Convierte las recepciones pendientes de stock_intercompany en traslados En camino.

        Por cada recepción vieja sin validar:
        - crea el traslado con lo pedido en la recepción (= lo que salió);
        - le engancha el picking de salida viejo, que ya descontó el origen;
        - pasa esa cantidad del tránsito viejo a "Traslados en camino";
        - cancela la recepción vieja (todavía no había sumado nada al destino).
        Se puede correr de nuevo: las recepciones ya migradas quedan canceladas.
        """
        Picking = self.env["stock.picking"].sudo()
        if "counterpart_of_picking_id" not in Picking._fields:
            raise UserError(_("stock_intercompany no está instalado: no hay nada para migrar."))
        receipts = Picking.search([
            ("counterpart_of_picking_id", "!=", False),
            ("state", "not in", ("done", "cancel")),
        ], order="id")
        transfers = self.browse()
        for receipt in receipts:
            transfers |= self._migrate_legacy_receipt(receipt)
        _logger.info("stock_branch_transfer: %s recepciones intercompany migradas", len(transfers))
        return transfers

    @api.model
    def _migrate_legacy_receipt(self, receipt):
        """Migra una recepción vieja a un traslado En camino (ver migrate_from_stock_intercompany)."""
        out = receipt.counterpart_of_picking_id
        if out.state != "done":
            raise UserError(_("La salida %s de la recepción %s no está validada.", out.name, receipt.name))
        Transfer = self.sudo().with_context(branch_transfer_internal=INTERNAL)
        lines = []
        for move in receipt.move_ids.filtered(lambda m: m.state != "cancel"):
            qty = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id)
            if float_is_zero(qty, precision_rounding=move.product_id.uom_id.rounding):
                continue
            lines.append((0, 0, {"product_id": move.product_id.id, "qty_sent": qty}))
        transfer = Transfer.create({
            "company_id": out.company_id.id,
            "dest_company_id": receipt.company_id.id,
            "line_ids": lines,
        })
        transfer.write({
            "state": "in_transit",
            "date_sent": out.date_done,
            "user_id": out.user_id.id or out.create_uid.id,
            "legacy_receipt_id": receipt.id,
        })
        out.branch_transfer_id = transfer
        for location in out.move_ids.location_dest_id:
            items = [
                (move.product_id, move.quantity)
                for move in out.move_ids.filtered(lambda m: m.location_dest_id == location and m.state == "done")
            ]
            transfer._create_legacy_transit_picking(location, out.picking_type_id, items)
        receipt.action_cancel()
        transfer._check_reconciled()
        transfer.message_post(body=_(
            "Migrado desde la recepción intercompany %(receipt)s (salida %(out)s).",
            receipt=receipt.name, out=out.name,
        ))
        receipt.message_post(body=_("Cancelada: migrada al traslado %s.", transfer.name))
        return transfer

    def _create_legacy_transit_picking(self, location, picking_type, items):
        """Mueve del tránsito viejo a "Traslados en camino", en la empresa de origen."""
        self.ensure_one()
        transit = self._transit_location()
        company = self.company_id
        picking = self.env["stock.picking"].sudo().with_company(company).create({
            "picking_type_id": picking_type.id,
            "location_id": location.id,
            "location_dest_id": transit.id,
            "company_id": company.id,
            "partner_id": False,
            "origin": self.name,
            "branch_transfer_id": self.id,
            "move_ids": [(0, 0, {
                "name": self.name,
                "product_id": product.id,
                "product_uom": product.uom_id.id,
                "product_uom_qty": qty,
                "location_id": location.id,
                "location_dest_id": transit.id,
                "company_id": company.id,
            }) for product, qty in items],
        })
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking._action_done()
        return picking

    def _check_reconciled(self):
        """Falla si lo movido no coincide con el objetivo del traslado (revierte la migración)."""
        for transfer in self:
            target, current = transfer._target_quantities(), transfer._current_quantities()
            for key in set(target) | set(current):
                product = self.env["product.product"].browse(key[0])
                if not float_is_zero(target[key] - current[key], precision_rounding=product.uom_id.rounding):
                    raise UserError(_(
                        "El traslado %(name)s quedaría descuadrado en %(product)s: esperado %(target)s, movido %(current)s.",
                        name=transfer.name, product=product.display_name,
                        target=target[key], current=current[key],
                    ))
