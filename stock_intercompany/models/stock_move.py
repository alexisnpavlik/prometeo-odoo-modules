# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

# Campos cuya escritura sobre un move de un picking validado exige el rol.
GUARDED_MOVE_FIELDS = ("product_uom_qty", "quantity", "product_id", "picked")


class StockMove(models.Model):
    _inherit = "stock.move"

    counterpart_of_move_id = fields.Many2one("stock.move", check_company=False)

    def write(self, vals):
        """Corta la edición de validados que no cumpla el rol."""
        if any(field in vals for field in GUARDED_MOVE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        return super().write(vals)
