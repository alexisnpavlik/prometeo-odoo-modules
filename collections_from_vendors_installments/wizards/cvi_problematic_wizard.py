# -*- coding: utf-8 -*-
from odoo import fields, models


class CviProblematicWizard(models.TransientModel):
    _name = "cvi.problematic.wizard"
    _description = "Marca de cliente problemático con su motivo"

    customer_id = fields.Many2one(
        "cvi.customer", string="Cliente", required=True, readonly=True,
    )
    reason = fields.Char(string="Motivo", required=True)

    def action_confirm_problematic(self):
        """Marca al cliente con el motivo escrito en el recuadro (HU-27)."""
        self.ensure_one()
        self.customer_id.action_mark_problematic(self.reason)
        return {"type": "ir.actions.act_window_close"}
