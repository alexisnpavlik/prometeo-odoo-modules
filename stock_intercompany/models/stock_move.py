# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

from .intercompany_sync import as_propagation, get_counterpart, is_propagation

# Campos cuya escritura sobre un move de un picking validado exige el rol.
GUARDED_MOVE_FIELDS = ("product_uom_qty", "quantity", "product_id", "picked")

# Campos del move que viajan al espejo.
#
# A diferencia de GUARDED_PICKING_FIELDS/SYNCED_PICKING_FIELDS en
# stock_picking.py, acá no se saltea la propagación cuando la contraparte
# también está en `self`: ese atajo de la Tarea 6 solo es correcto porque el
# valor que viaja es idéntico al escrito. product_uom_qty se propaga tal
# cual (mismo producto, misma UoM en las dos puntas, sin conversión), así
# que el atajo seguiría siendo válido en principio, pero no hay en este
# módulo ningún llamador que escriba en batch sobre moves de las dos puntas
# a la vez (a diferencia de stock.picking, donde sí lo ejercita un test real
# con (delivery | reception).write(...)): agregar el corte acá sería
# defensivo sin caso de uso ni cobertura. Si una tarea futura convierte el
# valor sincronizado a otra UoM antes de propagarlo, este atajo NO debe
# reutilizarse sin revisar: propagar el valor derivado sería incorrecto si
# el batch ya escribió el valor crudo en las dos puntas.
SYNCED_MOVE_FIELDS = ("product_uom_qty",)


class StockMove(models.Model):
    _inherit = "stock.move"

    counterpart_of_move_id = fields.Many2one("stock.move", check_company=False)

    def _get_counterpart_move(self):
        """Resuelve el move espejo en cualquiera de los dos sentidos."""
        return get_counterpart(self, "counterpart_of_move_id")

    def write(self, vals):
        """Corta la edición de validados sin rol y propaga la demanda al espejo.

        `touches_synced_fields`: mismo corte temprano que ya usa
        stock_picking.write() (y, desde esta ronda de corrección, también
        stock_move_line.write()). Ronda de corrección 1, Important 5:
        antes, el `for move in self: move._get_counterpart_move()` corría
        en TODO write(), tocara o no un campo sincronizado -y
        `get_counterpart()` hace un `search(limit=1)` por registro cuando
        el campo inverso está vacío, que es el caso de cualquier move sin
        espejo, o sea prácticamente todos los de la base-.
        `stock.move.write()` es uno de los caminos más calientes de Odoo
        (`moves_todo.write({'state': 'done', 'date': ...})` en
        `_action_done()` de core, por ejemplo, sobre TODOS los moves de
        cualquier picking que se valide, tenga o no espejo intercompany):
        sin este corte, cada validación de la base agregaba un SELECT
        extra por move.
        """
        if any(field in vals for field in GUARDED_MOVE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        if is_propagation(self.env):
            return super().write(vals)
        touches_synced_fields = bool(set(vals) & set(SYNCED_MOVE_FIELDS))
        previous = {}
        if touches_synced_fields:
            previous = {
                move.id: {field: move[field] for field in SYNCED_MOVE_FIELDS}
                for move in self
            }
        res = super().write(vals)
        if not touches_synced_fields:
            return res
        for move in self:
            counterpart = move._get_counterpart_move()
            if not counterpart:
                continue
            old = previous.get(move.id, {})
            changed = {
                field: move[field]
                for field in SYNCED_MOVE_FIELDS
                if field in old and move[field] != old[field]
            }
            if changed:
                as_propagation(counterpart).write(changed)
        return res
