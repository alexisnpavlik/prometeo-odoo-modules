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
# transferencia igual que la cantidad. product_id y move_id se agregan
# por el mismo criterio aunque no estén en "triggers": cambiar el
# producto o reparentar la línea a otro move también altera qué pasó
# realmente en la transferencia.
#
# picking_id queda deliberadamente AFUERA (ronda de corrección 2):
# stock.picking._create_backorder() (stock/models/stock_picking.py)
# reparenta las líneas del remanente al picking de backorder escribiendo
# picking_id DESPUÉS de que los moves originales ya están "done" —o sea
# con el picking origen ya en state "done" y, en un picking intercompany,
# con el espejo ya creado por nuestro _action_done. Vigilar picking_id
# bloqueaba con AccessError la creación de CUALQUIER backorder en una
# entrega intercompany parcial, para cualquier usuario sin el rol,
# incluido el operador normal que es justamente quien valida. No hay
# forma de distinguir "reparentado por mí, sin rol, para robar contenido
# de un validado" de "reparentado por el propio flujo de backorder de
# Odoo" mirando solo picking_id: hace falta vigilar por otro lado si
# algún día se necesita cerrar ese camino (por ejemplo evaluando el
# picking_id NUEVO, no el viejo). Por ahora se prioriza que la validación
# parcial funcione: ver test_operator_creates_backorder_without_role.
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
)


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    counterpart_of_line_id = fields.Many2one("stock.move.line", check_company=False)

    def write(self, vals):
        """Corta la edición de validados que no cumpla el rol."""
        if any(field in vals for field in GUARDED_LINE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        return super().write(vals)
