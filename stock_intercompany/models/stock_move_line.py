# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, fields, models

from .intercompany_sync import (
    as_propagation,
    get_counterpart,
    is_propagation,
    post_sync_note,
)

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

# Campos de la línea que viajan al espejo. Mismo criterio de no agregar el
# atajo "contraparte también en self" de la Tarea 6 que en stock_move.py: no
# hay en este módulo ningún llamador que escriba en batch sobre líneas de
# las dos puntas a la vez, y "quantity" viaja crudo (sin conversión de UoM
# entre las dos puntas), así que no hay valor derivado que ese atajo pudiera
# propagar mal.
SYNCED_LINE_FIELDS = ("quantity",)


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    counterpart_of_line_id = fields.Many2one("stock.move.line", check_company=False)

    def _get_counterpart_line(self):
        """Resuelve la línea espejo en cualquiera de los dos sentidos."""
        return get_counterpart(self, "counterpart_of_line_id")

    def write(self, vals):
        """Corta la edición de validados sin rol y propaga la cantidad al espejo.

        A diferencia de lo que asume ingenuamente cualquier atajo copiado
        sin verificar de otro módulo: acá SÍ se postea la nota también del
        lado que edita (`line.picking_id`), no solo del que recibe. Se
        comprobó contra el fuente de stock/models/stock_move_line.py (build
        de este contenedor) que stock.move.line no hereda mail.thread ni
        tiene tracking automático sobre "quantity" -no existe ningún
        "stock.track_move_template"-, así que sin esta nota el lado que
        edita se queda sin ningún rastro del cambio en su propio chatter.
        """
        if any(field in vals for field in GUARDED_LINE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        if is_propagation(self.env):
            return super().write(vals)
        previous = {
            line.id: {field: line[field] for field in SYNCED_LINE_FIELDS}
            for line in self
        }
        res = super().write(vals)
        for line in self:
            counterpart = line._get_counterpart_line()
            if not counterpart:
                continue
            old = previous.get(line.id, {})
            changed = {
                field: line[field]
                for field in SYNCED_LINE_FIELDS
                if field in old and line[field] != old[field]
            }
            if not changed:
                continue
            as_propagation(counterpart).write(changed)
            if "quantity" in changed and line.picking_id and counterpart.picking_id:
                body = _(
                    "%(product)s: cantidad %(old)s → %(new)s",
                    product=line.product_id.display_name,
                    old=old["quantity"],
                    new=changed["quantity"],
                )
                post_sync_note(line.picking_id, body)
                post_sync_note(
                    counterpart.picking_id, body, source_picking=line.picking_id
                )
        return res
