from odoo import _, api, fields, models
from odoo.tools import float_compare


class BranchTransferReceiveDiff(models.TransientModel):
    _name = "stock.branch.transfer.receive.diff"
    _description = "Recibir traslado con diferencias"

    transfer_id = fields.Many2one("stock.branch.transfer", string="Traslado", required=True)
    note = fields.Text(string="Nota")
    line_ids = fields.One2many("stock.branch.transfer.receive.diff.line", "wizard_id", string="Productos")

    @api.model
    def default_get(self, fields_list):
        """Precarga una línea por producto enviado, con lo recibido = lo enviado."""
        res = super().default_get(fields_list)
        transfer = self.env["stock.branch.transfer"].browse(res.get("transfer_id"))
        if transfer and "line_ids" in fields_list:
            res["line_ids"] = [(0, 0, {
                "transfer_line_id": line.id,
                "product_id": line.product_id.id,
                "qty_sent": line.qty_sent,
                "qty_received": line.qty_sent,
            }) for line in transfer.line_ids]
        return res

    def action_confirm(self):
        """Registra lo recibido; si hay diferencias el traslado queda pendiente."""
        self.ensure_one()
        transfer = self.transfer_id
        transfer._check_state("in_transit")
        transfer._check_company_access(transfer.dest_company_id)
        has_diff = False
        summary = []
        Line = self.env["stock.branch.transfer.line"].with_context(branch_transfer_internal=True)
        for wiz_line in self.line_ids:
            rounding = wiz_line.product_id.uom_id.rounding
            if wiz_line.transfer_line_id:
                wiz_line.transfer_line_id.with_context(branch_transfer_internal=True).qty_received = wiz_line.qty_received
                sent = wiz_line.transfer_line_id.qty_sent
            else:
                Line.create({
                    "transfer_id": transfer.id,
                    "product_id": wiz_line.product_id.id,
                    "qty_sent": 0.0,
                    "qty_received": wiz_line.qty_received,
                })
                sent = 0.0
            if float_compare(sent, wiz_line.qty_received, precision_rounding=rounding):
                has_diff = True
                summary.append(_("%(product)s: enviado %(sent)s, recibido %(received)s",
                                 product=wiz_line.product_id.display_name,
                                 sent=sent, received=wiz_line.qty_received))
        transfer._write_internal({
            "state": "with_diff" if has_diff else "received",
            "date_received": fields.Datetime.now(),
            "diff_note": self.note,
        })
        transfer._reconcile_stock()
        if has_diff:
            body = _("Recibido con diferencias:") + "<br/>" + "<br/>".join(summary)
            if self.note:
                body += "<br/>" + _("Nota: %s", self.note)
            transfer.message_post(body=body)
        return {"type": "ir.actions.act_window_close"}


class BranchTransferReceiveDiffLine(models.TransientModel):
    _name = "stock.branch.transfer.receive.diff.line"
    _description = "Línea de recepción con diferencias"

    wizard_id = fields.Many2one("stock.branch.transfer.receive.diff", required=True, ondelete="cascade")
    transfer_line_id = fields.Many2one("stock.branch.transfer.line")
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        domain=[("company_id", "=", False), ("type", "=", "consu"), ("is_storable", "=", True)],
    )
    qty_sent = fields.Float(string="Enviado", readonly=True, digits="Product Unit of Measure")
    qty_received = fields.Float(string="Recibido", digits="Product Unit of Measure")
