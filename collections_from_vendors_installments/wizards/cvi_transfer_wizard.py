# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CviTransferWizard(models.TransientModel):
    _name = "cvi.transfer.wizard"
    _description = "Transferencia de tarjetas entre cobradores"
    _inherit = ["cvi.wizard.mixin"]

    card_ids = fields.Many2many(
        "cvi.card",
        string="Tarjetas a transferir",
        domain="[('state', 'in', ('routed', 'active'))]",
    )
    collector_dest_id = fields.Many2one(
        "res.users",
        string="Cobrador destino",
        required=True,
        domain=lambda self: self._cvi_group_domain("group_cvi_collector"),
    )
    reason = fields.Char(string="Motivo de la transferencia", required=True)
    card_count = fields.Integer(string="Tarjetas seleccionadas", compute="_compute_card_count")

    @api.depends("card_ids")
    def _compute_card_count(self):
        """Cuántas tarjetas se van a transferir."""
        for wizard in self:
            wizard.card_count = len(wizard.card_ids)

    def action_confirm_transfer(self):
        """Pasa las tarjetas al cobrador destino dejando registro de la operación (HU-30).

        La tarjeta transferida conserva su estado: es una decisión de la administración,
        no un ofrecimiento que el cobrador destino deba aceptar.
        """
        self.ensure_one()
        if not self.card_ids:
            raise UserError(_("Seleccioná al menos una tarjeta para transferir."))
        if not self.reason or not self.reason.strip():
            raise UserError(_("Indicá el motivo de la transferencia."))
        wrong_state = self.card_ids.filtered(lambda c: c.state not in ("routed", "active"))
        if wrong_state:
            raise UserError(_(
                "Estas tarjetas no están en cobranza y no se pueden transferir: %s",
                ", ".join(wrong_state.mapped("name")),
            ))
        same = self.card_ids.filtered(lambda c: c.collector_id == self.collector_dest_id)
        if same:
            raise UserError(_(
                "Estas tarjetas ya están a cargo de %(collector)s: %(cards)s",
                collector=self.collector_dest_id.name,
                cards=", ".join(same.mapped("name")),
            ))
        reason = self.reason.strip()
        for card in self.card_ids:
            origin = card.collector_id
            card.collector_id = self.collector_dest_id
            card._cvi_log(_(
                "Tarjeta transferida de %(origin)s a %(dest)s por %(user)s. Motivo: %(reason)s",
                origin=origin.name or _("sin cobrador"),
                dest=self.collector_dest_id.name,
                user=self.env.user.name,
                reason=reason,
            ))
        return {"type": "ir.actions.act_window_close"}
