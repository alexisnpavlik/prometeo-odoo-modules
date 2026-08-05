# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

# Campos cuya escritura sobre una línea de un picking validado exige el rol.
GUARDED_LINE_FIELDS = ("quantity", "lot_id", "lot_name", "product_id")


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    counterpart_of_line_id = fields.Many2one("stock.move.line", check_company=False)

    def write(self, vals):
        """Corta la edición de validados que no cumpla el rol."""
        if any(field in vals for field in GUARDED_LINE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        return super().write(vals)
