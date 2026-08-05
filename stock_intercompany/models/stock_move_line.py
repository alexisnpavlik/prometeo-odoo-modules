# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

# Campos cuya escritura sobre una línea de un picking validado exige el rol.
#
# Coincide con la lista "triggers" de stock.move.line.write() core
# (location_id, location_dest_id, lot_id, package_id, result_package_id,
# owner_id, product_uom_id) más quantity: para una línea done, cualquiera
# de esos campos hace que Odoo deshaga y rehaga el movimiento de quants
# real (undo/redo), así que cambia el contenido efectivo de la
# transferencia igual que la cantidad. product_id, move_id y picking_id
# se agregan por el mismo criterio aunque no estén en "triggers": cambiar
# el producto, reparentar la línea a otro move o a otro picking valida
# también altera qué pasó realmente en la transferencia.
GUARDED_LINE_FIELDS = (
    "quantity",
    "lot_id",
    "lot_name",
    "product_id",
    "product_uom_id",
    "package_id",
    "result_package_id",
    "owner_id",
    "location_id",
    "location_dest_id",
    "move_id",
    "picking_id",
)


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    counterpart_of_line_id = fields.Many2one("stock.move.line", check_company=False)

    def write(self, vals):
        """Corta la edición de validados que no cumpla el rol."""
        if any(field in vals for field in GUARDED_LINE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        return super().write(vals)
