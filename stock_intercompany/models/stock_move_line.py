# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models

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
# "lot_id" (Tarea 9) se agrega para el corte temprano y la captura de
# `previous`/`old` en write(), pero NO para el diff genérico de abajo: no
# "viaja crudo" como quantity, porque stock.lot es un registro por
# compañía y el id de la línea de origen no sirve en la contraparte
# (ver RAW_COPY_LINE_FIELDS).
SYNCED_LINE_FIELDS = ("quantity", "lot_id")

# Subconjunto de SYNCED_LINE_FIELDS cuyo valor viaja tal cual al espejo, sin
# ninguna transformación. "lot_id" queda deliberadamente afuera: el diff
# genérico de más abajo compara `line[field] != old[field]` y copiaría el id
# crudo del lote de la compañía de ORIGEN, que no existe en la compañía
# destino. Se resuelve aparte, con map_lot(), en el bloque dedicado del
# write().
RAW_COPY_LINE_FIELDS = ("quantity",)


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    # copy=False: ver el comentario del campo homólogo en stock_picking.py
    # (review final, Important 4).
    counterpart_of_line_id = fields.Many2one(
        "stock.move.line", check_company=False, copy=False
    )

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

    @api.model_create_multi
    def create(self, vals_list):
        """Corta el alta de líneas sobre un picking validado o cancelado sin rol.

        Review final, Critical 2: hasta esta ronda, `stock.move.line` solo
        vigilaba `write()`. Pero core mueve los quants DENTRO del propio
        `create()` cuando la línea nace con `state == 'done'` -y una línea
        creada sobre un move de un picking ya validado nace así, porque el
        estado lo hereda del move-. O sea que crear una línea a mano sobre
        una entrega validada saca stock real sin pasar nunca por un
        `write()`. Reproducido con un usuario `stock.group_stock_user` sin
        el rol sobre una entrega intercompany validada: la línea se creó en
        `done` y el quant de origen bajó 3 unidades, sin AccessError y sin
        que el espejo recibiera nada.

        Mismo patrón que `stock_move.create()`: el chequeo corre ANTES de
        `super()`, para que el AccessError no deje una línea insertada, y
        el picking se resuelve primero por `vals['picking_id']` -que es lo
        que core siempre completa al armar líneas
        (`stock.move._prepare_move_line_vals`)- y solo si falta se paga la
        lectura del `move_id`, para no agregar un SELECT a cada creación de
        línea de la base.

        Alcance deliberado (declarado, no omitido): este override NO
        replica la línea nueva en la contraparte. El alta de una línea
        suelta sobre un move ya espejado no tiene una semántica única del
        otro lado -si el espejo está `assigned`, agregar una línea con
        cantidad no equivale a "recibir de más", y el flujo soportado para
        agregar contenido a un validado es el alta de un `stock.move`
        (`stock_move.create()` → `_bring_to_done()` →
        `_create_counterpart_move()`), que sí replica y deja nota-.
        Replicar acá arriesgaba duplicar cantidades en la punta espejo por
        un camino sin cobertura. Lo que esta ronda cierra es el bypass del
        rol, que era la parte de seguridad.
        """
        if not is_propagation(self.env) or not self.env.su:
            picking_ids = set()
            move_ids = set()
            for vals in vals_list:
                if vals.get("picking_id"):
                    picking_ids.add(vals["picking_id"])
                elif vals.get("move_id"):
                    move_ids.add(vals["move_id"])
            if move_ids:
                moves = self.env["stock.move"].sudo().browse(move_ids)
                picking_ids |= set(moves.mapped("picking_id").ids)
            if picking_ids:
                pickings = self.env["stock.picking"].browse(picking_ids)
                relevant = pickings.filtered(
                    lambda p: p.state in ("done", "cancel")
                )
                if relevant:
                    relevant._check_intercompany_edit_allowed()
        return super().create(vals_list)

    def write(self, vals):
        """Corta la edición de validados sin rol y propaga cantidad y lote al espejo.

        La nota de sync se postea SIEMPRE en las dos puntas -del lado que
        edita (`line.picking_id`) y del lado que recibe
        (`counterpart.picking_id`)-, conviva o no con el mensaje nativo de
        core en el lado `done` (ver `_quantity_change_logged_by_core`): son
        dos auditorías con propósitos distintos, la de core sobre el
        movimiento de stock, la nuestra sobre el contexto intercompany
        (qué picking y qué usuario de la OTRA compañía lo originó), y
        ninguna reemplaza a la otra. Esto vale igual para `quantity` que
        para `lot_id` (Tarea 9): `lot_id` es el primer campo de
        GUARDED_LINE_FIELDS que además se propaga, así que necesita la
        misma nota que `quantity`, no la ausencia de nota que tienen hoy el
        resto de los campos vigilados que no viajan al espejo.

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
                for field in RAW_COPY_LINE_FIELDS
                if field in old and line[field] != old[field]
            }
            if "lot_id" in vals:
                # Ronda de corrección 1 (Tarea 9), Minor 1: se compara el
                # lote YA MAPEADO contra el de la contraparte, no
                # `line.lot_id` (de la compañía de origen) contra
                # `counterpart.lot_id` (de la compañía destino) -esos dos
                # nunca son el mismo registro aunque representen "el mismo"
                # lote, así que esa comparación daba siempre verdadero y
                # forzaba un write sobre la contraparte (con el undo/redo
                # de quants que eso implica en una línea done) incluso
                # cuando el lote equivalente ya era el correcto.
                mapped = map_lot(line.lot_id, counterpart.company_id)
                if mapped != counterpart.lot_id:
                    changed["lot_id"] = mapped.id if mapped else False
            if not changed:
                continue
            as_propagation(counterpart).write(changed)
            if not (line.picking_id and counterpart.picking_id):
                continue
            if "quantity" in changed:
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
            if "lot_id" in changed:
                # Ronda de corrección 1 (Tarea 9), Critical 2: a diferencia
                # de los demás campos de GUARDED_LINE_FIELDS -que hoy no se
                # propagan-, un write de lot_id SÍ cambia stock ya validado
                # de la otra compañía (undo/redo de quants incluido), así
                # que necesita la misma nota de auditoría que quantity: el
                # mensaje propio de core no nombra ni el picking de origen
                # ni la compañía, que es justo la mitigación que exige el
                # riesgo aceptado de este módulo (operador de B corrigiendo
                # stock validado de A).
                old_lot = old.get("lot_id")
                body = _(
                    "%(product)s: lote %(old)s → %(new)s",
                    product=line.product_id.display_name,
                    old=old_lot.display_name if old_lot else _("sin lote"),
                    new=line.lot_id.display_name if line.lot_id else _("sin lote"),
                )
                post_sync_note(line.picking_id, body)
                post_sync_note(
                    counterpart.picking_id, body, source_picking=line.picking_id
                )
        return res
