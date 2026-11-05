# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

LOCKED_WRITE_FIELDS = {"line_ids", "partner_id", "account_id"}


class CcaWithdrawal(models.Model):
    _inherit = "cca.withdrawal"

    pos_order_id = fields.Many2one(
        "pos.order", string="Pedido del POS", readonly=True, index=True, copy=False,
        help="Pedido del POS que originó el retiro. Su albarán ya movió el stock.",
    )

    def _cca_pos_blocked_error(self, withdrawal):
        """UserError estándar: el retiro del POS se anula con un reembolso."""
        return UserError(_(
            "El retiro %s nació en el POS: anulalo con un reembolso del pedido %s.",
            withdrawal.name, withdrawal.pos_order_id.pos_reference or withdrawal.pos_order_id.name,
        ))

    def _cca_create_sale_order(self):
        """Retiro del POS: toma el albarán del pedido y no crea venta; si no, el flujo base."""
        self.ensure_one()
        if not self.pos_order_id:
            return super()._cca_create_sale_order()
        self.picking_id = self.pos_order_id.picking_ids[:1]
        return False

    def _cca_return_picking(self):
        """Retiro del POS: el stock lo devuelve el reembolso, no este retiro."""
        self.ensure_one()
        if self.pos_order_id:
            return False
        return super()._cca_return_picking()

    def action_cancel(self):
        """Bloquea la cancelación de retiros del POS salvo desde un reembolso."""
        if not self.env.context.get("cca_pos_refund"):
            for withdrawal in self.filtered("pos_order_id"):
                raise self._cca_pos_blocked_error(withdrawal)
        return super().action_cancel()

    def action_draft(self):
        """Los retiros del POS no vuelven a borrador."""
        for withdrawal in self.filtered("pos_order_id"):
            raise self._cca_pos_blocked_error(withdrawal)
        return super().action_draft()

    def action_edit(self):
        """Retiros del POS: solo vencimientos, nunca vuelven a borrador."""
        pos_withdrawals = self.filtered("pos_order_id")
        for withdrawal in pos_withdrawals:
            if withdrawal.state not in ("pending", "partial", "paid"):
                raise UserError(_("Solo se puede editar un retiro confirmado."))
            withdrawal.edit_due_dates = True
        return super(CcaWithdrawal, self - pos_withdrawals).action_edit()

    def write(self, vals):
        """Un retiro del POS confirmado no cambia de líneas, cliente ni cuenta."""
        if LOCKED_WRITE_FIELDS & set(vals) and any(w.pos_order_id and w.is_confirmed for w in self):
            raise UserError(_(
                "Un retiro nacido en el POS no se puede modificar: las líneas, el cliente y la "
                "cuenta vienen del pedido."
            ))
        return super().write(vals)

    def action_view_pos_order(self):
        """Abre el pedido del POS que originó el retiro."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Pedido de %s", self.name),
            "res_model": "pos.order",
            "res_id": self.pos_order_id.id,
            "view_mode": "form",
        }
