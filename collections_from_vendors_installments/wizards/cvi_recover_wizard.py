# -*- coding: utf-8 -*-
from odoo import fields, models


class CviRecoverWizard(models.TransientModel):
    _name = "cvi.recover.wizard"
    _description = "Marca de retiro del mueble con su motivo"

    card_id = fields.Many2one(
        "cvi.card", string="Tarjeta", required=True, readonly=True,
    )
    reason = fields.Char(string="Motivo del retiro", required=True)

    def action_confirm_recover(self):
        """Marca la tarjeta para retiro con el motivo escrito en el recuadro (HU-25)."""
        self.ensure_one()
        self.card_id.action_mark_to_recover(self.reason)
        return {"type": "ir.actions.act_window_close"}
