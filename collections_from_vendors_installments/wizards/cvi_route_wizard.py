# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CviRouteWizard(models.TransientModel):
    _name = "cvi.route.wizard"
    _description = "Enrutamiento en lote de tarjetas a un cobrador"
    _inherit = ["cvi.wizard.mixin"]

    card_ids = fields.Many2many(
        "cvi.card",
        string="Tarjetas a enviar",
        domain="[('state', '=', 'sold')]",
    )
    collector_id = fields.Many2one(
        "res.users",
        string="Cobrador",
        required=True,
        domain=lambda self: self._cvi_group_domain("group_cvi_collector"),
    )
    card_count = fields.Integer(string="Tarjetas seleccionadas", compute="_compute_card_count")

    @api.depends("card_ids")
    def _compute_card_count(self):
        """Cuántas tarjetas se van a enviar, para confirmarlo antes de ejecutar."""
        for wizard in self:
            wizard.card_count = len(wizard.card_ids)

    def action_confirm_route(self):
        """Asigna el cobrador y enruta todas las tarjetas en una sola operación (HU-11).

        La asignación del cobrador se hace con un único write sobre todo el recordset,
        y el cambio de estado en un solo recorrido, para que 100+ tarjetas no degraden (RNF-05).
        """
        self.ensure_one()
        if not self.card_ids:
            raise UserError(_("Seleccioná al menos una tarjeta para enviar."))
        wrong_state = self.card_ids.filtered(lambda c: c.state != "sold")
        if wrong_state:
            raise UserError(_(
                "Estas tarjetas no están en estado Vendida y no se pueden enviar: %s",
                ", ".join(wrong_state.mapped("name")),
            ))
        self.card_ids.write({"collector_id": self.collector_id.id})
        self.card_ids.action_route()
        return {"type": "ir.actions.act_window_close"}
