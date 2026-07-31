# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class CviRejectWizard(models.TransientModel):
    _name = "cvi.reject.wizard"
    _description = "Rechazo de tarjetas enrutadas"

    card_ids = fields.Many2many(
        "cvi.card",
        string="Tarjetas",
        required=True,
        domain="[('state', '=', 'routed')]",
    )
    reason = fields.Char(string="Motivo del rechazo", required=True)

    def action_confirm_reject(self):
        """Aplica el mismo motivo de rechazo a todas las tarjetas seleccionadas."""
        self.ensure_one()
        if not self.card_ids:
            raise UserError(_("Seleccioná al menos una tarjeta para rechazar."))
        self.card_ids.action_reject(self.reason)
        return {"type": "ir.actions.act_window_close"}
