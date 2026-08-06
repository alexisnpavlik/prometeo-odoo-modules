# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, fields, models

from .intercompany_sync import (
    as_propagation,
    get_counterpart,
    is_propagation,
    map_lot,
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
#
# "lot_id" (Tarea 9) es la excepción a "viaja crudo": stock.lot es un
# registro por compañía, así que el id de la línea de origen no sirve en la
# contraparte. El bucle de write() de abajo no copia line.lot_id tal cual,
# lo resuelve con map_lot() al lote equivalente de la compañía destino
# antes de armar `changed`.
SYNCED_LINE_FIELDS = ("quantity", "lot_id")


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    counterpart_of_line_id = fields.Many2one("stock.move.line", check_company=False)

    def _get_counterpart_line(self):
        """Resuelve la línea espejo en cualquiera de los dos sentidos."""
        return get_counterpart(self, "counterpart_of_line_id")

    def _quantity_change_logged_by_core(self):
        """Verdadero si Odoo ya audita este cambio de `quantity` en su propio chatter.

        `stock.move.line.write()` (stock/models/stock_move_line.py de este
        build, alrededor de la línea 517) hace `ml._log_message(ml.picking_id,
        ml, 'stock.track_move_template', vals)` para toda línea cuyo
        `move_id.state == 'done'` y producto almacenable, cuando `vals` toca
        `quantity`.

        Ronda de corrección 1 (Important 4): esto se usó para SUPRIMIR la
        nota propia del lado `done`, asumiendo que evitar la duplicación
        con el mensaje de core alcanzaba. Ronda de corrección 2: esa
        instrucción del coordinador estaba equivocada y se revirtió — el
        spec del módulo exige que TODO lo que se propaga deje nota en las
        dos puntas, y que la de la contraparte nombre el picking de origen
        y el usuario que lo hizo. Es la mitigación explícita de un riesgo
        aceptado en el diseño: un operador de la compañía B (sin rol ni
        acceso a la compañía A) modificando stock ya validado y valorizado
        de la compañía A. La entrega SIEMPRE es la punta `done` -el caso
        normal-, y el mensaje genérico de core ("The done move line has
        been corrected.") no nombra ni el picking contraparte ni la
        compañía de origen: suprimir la nota propia ahí perdía justo la
        trazabilidad que justificaba aceptar el riesgo. Ahora este método
        se usa solo para que los tests sepan cuántos mensajes esperar de
        cada lado (el propio siempre, más el de core cuando corresponde),
        no para decidir si postear.
        """
        self.ensure_one()
        return self.move_id.state == "done" and self.product_id.is_storable

    def write(self, vals):
        """Corta la edición de validados sin rol y propaga la cantidad al espejo.

        La nota de sync se postea SIEMPRE en las dos puntas -del lado que
        edita (`line.picking_id`) y del lado que recibe
        (`counterpart.picking_id`)-, conviva o no con el mensaje nativo de
        core en el lado `done` (ver `_quantity_change_logged_by_core`): son
        dos auditorías con propósitos distintos, la de core sobre el
        movimiento de stock, la nuestra sobre el contexto intercompany
        (qué picking y qué usuario de la OTRA compañía lo originó), y
        ninguna reemplaza a la otra.

        `touches_synced_fields`: igual que en stock_picking.py, el diff y
        la búsqueda de contraparte (`_get_counterpart_line`, que hace un
        `search()` cuando el campo inverso está vacío -el caso de
        CUALQUIER línea sin espejo, o sea casi todas las de la base-) solo
        se ejecutan cuando `vals` toca algún campo sincronizado. `write()`
        de stock.move.line es uno de los caminos más calientes de Odoo
        (`moves_todo.write({'state': 'done', 'date': ...})` sobre un
        picking de 200 líneas, por ejemplo); sin este corte, cada
        escritura -toque o no `quantity`- agregaba un SELECT extra por
        línea sobre TODA la base, tenga o no espejo intercompany.
        """
        if any(field in vals for field in GUARDED_LINE_FIELDS):
            self.picking_id._check_intercompany_edit_allowed()
        if is_propagation(self.env):
            return super().write(vals)
        touches_synced_fields = bool(set(vals) & set(SYNCED_LINE_FIELDS))
        previous = {}
        if touches_synced_fields:
            previous = {
                line.id: {field: line[field] for field in SYNCED_LINE_FIELDS}
                for line in self
            }
        res = super().write(vals)
        if not touches_synced_fields:
            return res
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
            if "lot_id" in vals and line.lot_id != counterpart.lot_id:
                mapped = map_lot(line.lot_id, counterpart.company_id)
                changed["lot_id"] = mapped.id if mapped else False
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
