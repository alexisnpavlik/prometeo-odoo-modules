# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .intercompany_sync import (
    as_propagation,
    get_counterpart,
    is_propagation,
    map_lot,
    post_sync_note,
)

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

    # copy=False: ver el comentario del campo homólogo en stock_picking.py
    # (review final, Important 4). Duplicar el picking espejo copiaba el
    # vínculo de los 32 moves hacia los moves de la entrega validada.
    counterpart_of_move_id = fields.Many2one(
        "stock.move", check_company=False, copy=False
    )

    def _get_counterpart_move(self):
        """Resuelve el move espejo en cualquiera de los dos sentidos."""
        return get_counterpart(self, "counterpart_of_move_id")

    @api.model_create_multi
    def create(self, vals_list):
        """Lleva a done los moves agregados a un picking ya validado y los replica.

        El corte por `picking.state in ("done", "cancel")` no es solo un
        filtro de alcance: es lo que evita dispararse a sí mismo. Este
        mismo `create()` también corre cuando el propio módulo arma el
        espejo inicial (`_create_counterpart_picking`, moves anidados
        dentro de un picking que nace en `draft` con
        `counterpart_of_picking_id` ya seteado) y cuando core parte moves
        al generar un backorder (picking de backorder en
        `assigned`/`confirmed`, nunca `done` ni `cancel`). En ninguno de
        esos dos caminos el picking del move recién creado está en uno de
        esos dos estados todavía, así que quedan afuera de este bloque sin
        necesidad de otro flag de contexto. La única puerta genuina que sí
        hay que cortar con el flag existente es la propagación propia:
        `_create_counterpart_move()` crea el espejo con `as_propagation`,
        que ya viene cubierta por el `is_propagation` de más arriba.

        Ronda de corrección 1, Important 4: el chequeo de estado va
        PRIMERO -antes de mirar `counterpart_picking_id`-, tanto acá como
        en el bloque de permisos previo al `super().create()`.
        `counterpart_picking_id` es un compute no almacenado que hace un
        `search()` cuando el campo inverso está vacío (el caso de
        prácticamente cualquier picking sin espejo, o sea casi todos los
        de la base): evaluarlo antes del filtro barato por estado agrega
        un SELECT extra a TODA creación de move de la base, incluida la
        de un `stock.move.create()` masivo al confirmar una venta común.
        Es la misma regresión que ya se corrigió dos veces en el
        `write()` de move y de move line.

        Ronda de corrección 1, Important 3 (nota de alcance): el chequeo
        de rol (`_check_intercompany_edit_allowed`) corre ANTES de
        `super().create()`, sobre los pickings de `vals_list`, para que un
        `AccessError` por falta de rol no deje insertado un move fantasma
        -si un caller externo capturara el `AccessError` en vez de dejar
        que la transacción entera hiciera rollback, ese move ya `done`
        quedaría en el picking sin que nadie lo haya autorizado-.

        Ronda de corrección 1, Important 1 (por qué el rechazo de
        `cancel` también va ANTES de crear, no solo el chequeo de rol):
        la primera versión de este fix dejaba pasar la creación y recién
        después comparaba `move.picking_id.state == "cancel"` -pero para
        ese momento el `_compute_state` de core YA había recalculado el
        picking, porque insertar el move nuevo (que nace `draft`, ya que
        el picking no está `done`) le gana a `all_cancel` en el cómputo
        (`any_draft` tiene prioridad). O sea que un manager CON el rol
        pasaba el chequeo de acceso, se insertaba el move, y para cuando
        se evaluaba el estado ya decía `draft`, no `cancel`: el bloqueo
        nunca se disparaba. Reproducido con un test que falla así antes
        de este ajuste. Rechazar el estado `cancel` en el mismo bucle que
        el chequeo de rol, antes de tocar `super().create()`, evita que
        la propia inserción cambie la respuesta a la pregunta que se está
        haciendo.
        """
        if not is_propagation(self.env):
            picking_ids = {
                vals["picking_id"] for vals in vals_list if vals.get("picking_id")
            }
            for picking in self.env["stock.picking"].browse(picking_ids):
                if picking.state not in ("done", "cancel"):
                    continue
                if not picking.counterpart_picking_id:
                    continue
                picking._check_intercompany_edit_allowed()
                if picking.state == "cancel":
                    raise UserError(
                        _(
                            "No se puede agregar productos a %(name)s: la "
                            "transferencia está cancelada.",
                            name=picking.name,
                        )
                    )
        moves = super().create(vals_list)
        if is_propagation(self.env):
            return moves
        for move in moves:
            picking = move.picking_id
            if not picking or picking.state != "done":
                continue
            if not picking.counterpart_picking_id:
                continue
            move._bring_to_done()
            move._create_counterpart_move()
            body = _(
                "Línea agregada: %(product)s x %(qty)s",
                product=move.product_id.display_name,
                qty=move.product_uom_qty,
            )
            post_sync_note(picking, body)
            post_sync_note(
                picking.counterpart_picking_id, body, source_picking=picking
            )
        return moves

    def _bring_to_done(self):
        """Lleva el move a `done` por la vía normal de Odoo, sin tocar quants.

        Ronda de corrección 1, "cosas chicas" 2: el docstring original
        describía la intención (apoyarse en el flujo estándar de Odoo)
        pero no lo que realmente pasa acá. Un move creado sobre un
        picking ya `done` nace `done` DESDE `super().create()` -core
        fuerza `vals['state'] = 'done'` cuando `picking_id.state ==
        'done'`, stock/models/stock_move.py-, así que `_action_confirm()`,
        `_action_assign()` y `_action_done()` de acá abajo son NO-OPS: los
        tres filtran por `state == 'draft'`/`state not in ('done',
        'cancel')` y no encuentran nada que hacer. Lo único que mueve
        stock de verdad es `move.quantity = move.product_uom_qty`: dispara
        el inverse de core (`_set_quantity` → `_set_quantity_done`), que
        crea la `stock.move.line` que falta -sin necesidad de que
        `_action_assign()` haya reservado nada antes- y, al nacer esa
        línea con `state == 'done'` (heredado del move), su propio
        `create()` (stock/models/stock_move_line.py) es quien mueve los
        quants reales en origen y destino. Se dejan las cuatro llamadas
        igual, no solo por si algún día un move llega acá sin nacer
        `done` (por ejemplo si core cambia esa lógica), sino porque es la
        forma documentada y soportada de editar un move `done` -no un
        atajo de este módulo-.

        Ronda de corrección 1, Important 3: si el producto usa lote o
        número de serie, este flujo NUNCA pasa por
        `stock.move.line._action_done()` (que es donde vive el chequeo
        de core "hace falta un lote"): `_action_done()` de arriba filtra
        los moves que ya están `done` antes de llegar a esa validación.
        Sin este chequeo explícito, un producto trazado se daba por
        `done` sin lote, silenciosamente. Se exige acá: quien agregue la
        línea tiene que crearla con `move_line_ids` y el `lot_id`/
        `lot_name` ya resuelto (Odoo no puede inferirlo solo en este
        camino, a diferencia de la reserva normal contra picking types
        con `use_create_lots`).
        """
        for move in self:
            move._action_confirm()
            move._action_assign()
            lines_without_lot = move.move_line_ids.filtered(
                lambda line: not line.lot_id
            )
            if move.product_id.tracking != "none" and (
                not move.move_line_ids or lines_without_lot
            ):
                raise UserError(
                    _(
                        # Review final, one-liner 3: el mensaje decía
                        # "lot_id/lot_name" pero el filtro de arriba solo
                        # mira lot_id, y tiene que seguir siendo así: en
                        # este camino `_action_done()` es un no-op (el move
                        # ya nace done), así que nadie convierte lot_name en
                        # un stock.lot real y la línea quedaría done con el
                        # quant sin lote. Se corrige el mensaje, no el
                        # filtro.
                        "%(product)s usa lote o número de serie: hay que "
                        "indicar el lote ya creado (línea con lot_id) al "
                        "agregarlo a una transferencia ya validada.",
                        product=move.product_id.display_name,
                    )
                )
            move.quantity = move.product_uom_qty
            move.picked = True
            move._action_done()

    def _create_counterpart_move(self):
        """Crea el move espejo en la contraparte, replicando su estado.

        Devuelve el move creado, o un recordset vacío si ya existía (por
        ejemplo, si `_create_counterpart_move` se llama dos veces sobre el
        mismo move por error de un caller). Las líneas nacen con
        `picking_id=False` porque el ORM solo completa el inverso del
        o2m que se anida (`move_id`, vía `move_line_ids`): hay que
        repararlo a mano después, igual que hace
        `stock.picking._create_counterpart_picking()` con su propio
        builder (ver el docstring de `_get_counterpart_move_commands`).

        Ronda de corrección 1, Important 2: si la contraparte está
        `cancel`, no hay ninguna réplica de sentido -propagar hacia un
        documento cancelado no mueve nada de verdad ahí, y "reabrirlo"
        solo (como en Important 1) deja el picking espejo en un estado
        que nadie decidió-. Se corta ANTES de crear nada: `self` (el
        move de origen) ya quedó `done` por `_bring_to_done()` en el
        `create()` que llama a este método, así que levantar acá un
        `UserError` hace que toda la transacción -incluida esa
        validación del origen- haga rollback, en vez de dejar las dos
        puntas divergentes (origen `done` con stock movido, contraparte
        todavía `cancel` con la línea vieja).
        """
        self.ensure_one()
        counterpart_picking = self.picking_id.counterpart_picking_id
        if not counterpart_picking or self._get_counterpart_move():
            return self.browse()
        if counterpart_picking.state == "cancel":
            raise UserError(
                _(
                    "La contraparte %(name)s está cancelada: no se puede "
                    "replicar el alta de %(product)s sin reabrirla a mano "
                    "primero.",
                    name=counterpart_picking.name,
                    product=self.product_id.display_name,
                )
            )
        company = counterpart_picking.company_id
        line_commands = []
        for line in self.move_line_ids:
            lot = map_lot(line.lot_id, company)
            line_commands.append(
                Command.create(
                    {
                        "product_id": line.product_id.id,
                        "product_uom_id": line.product_uom_id.id,
                        "quantity": line.quantity,
                        "lot_id": lot.id if lot else False,
                        "location_id": counterpart_picking.location_id.id,
                        "location_dest_id": counterpart_picking.location_dest_id.id,
                        "company_id": company.id,
                        "counterpart_of_line_id": line.id,
                    }
                )
            )
        counterpart = (
            as_propagation(self.env["stock.move"])
            .with_company(company)
            .create(
                {
                    "picking_id": counterpart_picking.id,
                    "product_id": self.product_id.id,
                    "product_uom": self.product_uom.id,
                    "product_uom_qty": self.product_uom_qty,
                    "name": self.name,
                    "company_id": company.id,
                    "location_id": counterpart_picking.location_id.id,
                    "location_dest_id": counterpart_picking.location_dest_id.id,
                    "picking_type_id": counterpart_picking.picking_type_id.id,
                    "counterpart_of_move_id": self.id,
                    "move_line_ids": line_commands,
                }
            )
        )
        # Reparación obligatoria: ver el docstring de arriba.
        counterpart.move_line_ids.picking_id = counterpart_picking.id
        if counterpart_picking.state == "done":
            as_propagation(counterpart)._bring_to_done()
        else:
            as_propagation(counterpart)._action_confirm()
        return counterpart

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
            if not changed:
                continue
            as_propagation(counterpart).write(changed)
            # Review final, Important 5: la demanda se propagaba en
            # silencio. El §9 del spec exige nota en las DOS puntas para
            # todo lo que viaja al espejo, y `product_uom_qty` estaba
            # listado en el §7.1 como sincronizado: un manager bajaba la
            # demanda de la entrega validada de 10 a 8, la demanda de la
            # recepción de la otra compañía cambiaba sola, y no quedaba
            # nada escrito en ningún chatter. Es exactamente la contención
            # que el §3.2 exige para haber aceptado el riesgo de que un
            # operador de una compañía modifique documentos de la otra.
            # Mismo patrón que `stock_move_line.write`.
            if not (move.picking_id and counterpart.picking_id):
                continue
            if "product_uom_qty" in changed:
                body = _(
                    "%(product)s: demanda %(old)s → %(new)s",
                    product=move.product_id.display_name,
                    old=old["product_uom_qty"],
                    new=changed["product_uom_qty"],
                )
                post_sync_note(move.picking_id, body)
                post_sync_note(
                    counterpart.picking_id, body, source_picking=move.picking_id
                )
        return res

    def action_intercompany_void(self):
        """Anula la línea dejándola en cero, en las dos puntas.

        Un move en `done` no se puede borrar sin perder la trazabilidad
        del movimiento original: "eliminar" pasa a significar demanda y
        cantidad hecha en cero. `move.move_line_ids.write(...)` y
        `move.write(...)` son escrituras NORMALES -no en
        sudo/propagación-: pasan por el `write()` ya existente de
        stock.move.line y stock.move (`quantity` y `product_uom_qty`
        están en SYNCED_LINE_FIELDS/SYNCED_MOVE_FIELDS), que YA revierte
        los quants reales (undo/redo del core) y YA propaga el valor al
        espejo con su propia nota de auditoría ("cantidad %s → %s"): no
        hace falta duplicar esa propagación a mano acá. Lo único que
        agrega este método es la nota semántica "línea anulada" -distinta
        de la de cantidad: documenta que además se puso la demanda en
        cero, no solo la cantidad hecha- y el chequeo de rol explícito,
        necesario porque este método es público y la UI (o un caller
        externo) puede invocarlo directo, sin pasar por `unlink()`.

        Ronda de corrección 1 (revisor), Critical 1: el chequeo de rol
        mira las DOS puntas -la propia y la de la contraparte-, no solo
        `move.picking_id`. Es el mismo agujero que ya se había cerrado en
        `unlink()` pero que este método, siendo la puerta pública que
        `unlink()` termina usando, había dejado abierta: un operador SIN
        rol podía invocar `action_intercompany_void()` directo sobre una
        línea de una recepción sin validar (su propio picking no está
        done/cancel, así que un chequeo de una sola punta lo dejaba
        pasar) cuya contraparte -la entrega- YA está done, y revertir
        stock real ya validado de la otra compañía sin autorización.
        Reproducido por el revisor antes de este fix: `cp: quantity 30.0
        -> 0.0` con un usuario sin `group_intercompany_manager`.
        """
        for move in self:
            picking = move.picking_id
            counterpart = move._get_counterpart_move()
            guard_pickings = picking
            if counterpart and counterpart.picking_id:
                guard_pickings |= counterpart.picking_id
            guard_pickings._check_intercompany_edit_allowed()
            move.move_line_ids.write({"quantity": 0.0})
            move.write({"product_uom_qty": 0.0})
            body = _(
                "Línea anulada: %(product)s",
                product=move.product_id.display_name,
            )
            post_sync_note(picking, body)
            if counterpart and counterpart.picking_id:
                post_sync_note(
                    counterpart.picking_id, body, source_picking=picking
                )
        return True

    def _merge_moves(self, merge_into=False):
        """Fusiona moves duplicados (core) sin disparar la cascada de
        baja/anulación de este módulo.

        Ronda de corrección 1 (revisor), Important 3 + su seguimiento
        sobre el orden de `groupby`: `_merge_moves` (core,
        stock/models/stock_move.py) puede fusionar dos moves "duplicados"
        del mismo picking/producto/ubicaciones en uno solo, borrando el
        sobrante con `moves_to_unlink.sudo().unlink()`. Antes de este fix,
        ese `unlink()` cascadeaba como cualquier baja real -y CUÁL de los
        dos moves fusionados sobrevive (`moves[0]`) depende del orden
        natural de `picking.move_ids` en el `groupby` de core, que no está
        garantizado ni documentado como estable-: si el que se BORRA es el
        que tenía contraparte `done` con stock real, la cascada de este
        módulo la anulaba en silencio -no una nota espuria, sino el
        Critical real: revertir stock validado sin que nadie lo pida-; si
        el que se borra es el que no tenía contraparte, el síntoma es más
        leve (una nota "Línea eliminada" espuria) pero sigue siendo
        incorrecto -nadie borró nada de verdad, fue bookkeeping interno de
        Odoo-. Reproducido por el revisor en contexto NORMAL (no
        propagado): agregar una línea del mismo producto a una recepción
        espejo y correr `action_confirm()` a mano ya dispara la fusión sin
        pasar por ninguno de los caminos `as_propagation(...)` de este
        módulo.

        Se corre TODO el método bajo `skip_intercompany_sync` -el único
        flag de contexto del módulo- para que cualquier `unlink()` que
        dispare puertas adentro, sea cual sea el move que sobreviva, tome
        la rama de propagación (mutación local pura, sin resolver
        contraparte ni postear nota): el resultado deja de depender del
        orden interno de `groupby`. Efecto colateral aceptado: si el move
        sobreviviente YA tenía contraparte propia y la fusión le cambia
        `product_uom_qty` (demanda combinada), ese cambio no se propaga
        solo a su contraparte durante la fusión -no es un caso cubierto ni
        testeado por este módulo, y es preferible a arriesgar la cascada
        espuria descrita arriba-.
        """
        return super(
            StockMove, self.with_context(skip_intercompany_sync=True)
        )._merge_moves(merge_into=merge_into)

    def unlink(self):
        """Borra en cascada al espejo; en pickings validados o cancelados
        anula (o exige rol) en vez de borrar directo.

        Corte temprano barato: la resolución real de la contraparte -que
        implica un `search()` cuando el picking no es él mismo el espejo,
        ver `get_counterpart()` en intercompany_sync.py- solo se paga
        para los moves cuyo picking PUEDE de verdad tener una. Una
        recepción espejo lo dice sin buscar nada (`counterpart_of_picking_id`
        propio, siempre seteado desde que se crea); una entrega solo tiene
        espejo una vez `done` (se crea recién en `_action_done()`), así
        que cualquier picking en `draft`/`confirmed`/`assigned` que
        además no es él mismo un espejo no puede tener contraparte y se
        descarta sin tocar la base -mismo criterio de corte barato que ya
        usan los `write()` de los tres modelos-. `cancel` se incluye igual
        que `done` -ronda de corrección 1, Minor 3-: aunque una entrega
        con contraparte real nunca puede llegar a `cancel` (core no deja
        cancelar un picking `done`), es el estado que el guard de abajo
        pretende cubrir explícitamente, y dejarlo fuera del corte barato
        sería inconsistente con esa intención aunque hoy no sea
        alcanzable.

        La decisión de anular en vez de borrar se toma SIEMPRE mirando el
        estado de la punta que efectivamente se está por tocar, no el de
        la punta que el usuario editó directo: si se borra una línea
        todavía sin validar (p. ej. una recepción `assigned`) cuya
        contraparte YA está `done` -el caso normal, porque una entrega
        con espejo está siempre `done`-, esa contraparte no se puede
        borrar sin perder trazabilidad y se anula en vez de eliminarse,
        aunque el lado que el usuario tocó sí se borre entero. Por eso el
        chequeo de rol también mira el estado de la CONTRAPARTE, no solo
        el propio: sin esto, un operador sin rol podía anular stock ya
        validado de la otra compañía con solo borrar una línea pendiente
        de su lado.

        Ronda de corrección (revisión propia, Important): la propagación
        hacia la contraparte se hace llamando de nuevo a `unlink()` en
        sudo/propagación (`as_propagation`) en vez de siempre borrar
        crudo: la llamada recursiva vuelve a evaluar el estado de ESA
        punta y aplica la misma regla done→anular / resto→borrar del lado
        que le toca, sin duplicar la lógica ni arriesgar un `unlink()` de
        un move `done` de la otra compañía (que dejaría sus quants sin
        revertir: core solo bloquea el borrado de un move done con
        `move_orig_ids`/`move_dest_ids`, no el de cualquier move done).

        Orden: se resuelve la contraparte y se posta la nota ANTES de
        borrar nada -después del borrado del original el vínculo ya no
        existe-, y se borra primero el lado que el usuario tocó
        directamente (el que más probablemente dispare una restricción
        core como `_unlink_if_draft_or_cancel`) antes de propagar hacia
        la contraparte: si el borrado del propio lado falla, la
        contraparte de la otra compañía queda sin tocar.

        Ronda de corrección 1 (revisor), Critical 2: cuando se borra un
        PICKING entero -core, `stock.picking.unlink()`
        (stock/models/stock_picking.py), hace `self.move_ids.unlink()`
        con TODOS los moves de esos pickings a la vez, ANTES de borrar el
        registro del picking- no hay que cascadear nada hacia la
        contraparte: es limpieza administrativa de un documento
        (típicamente cancelado o draft), no una baja de línea deliberada.
        Sin este corte, borrar una recepción espejo cancelada -limpieza
        rutinaria de un manager- anulaba en silencio (revertía quants de
        verdad) la entrega YA VALIDADA de la otra compañía, sin que nadie
        lo pidiera.

        Un primer intento detectaba esto comparando, por picking, si el
        conjunto de moves que se están borrando ahora coincide con TODOS
        los moves de ese picking -la firma de `self.move_ids.unlink()`-,
        pero es un FALSO POSITIVO cuando el picking tiene un solo move:
        borrar directo LA ÚNICA línea de un picking (`move.unlink()`, no
        `picking.unlink()`) también cumple esa condición, y quedaba sin
        cascada por error (reproducido: `test_unlink_on_validated_voids_instead`
        y análogos empezaban a fallar). La detección correcta vive en
        `stock.picking.unlink()` (`models/stock_picking.py`), que es
        quien sabe de verdad que el picking ENTERO se está por borrar: ese
        override envuelve su propio `self.move_ids.unlink()` con
        `skip_intercompany_sync`, así que estos moves llegan acá con
        `is_propagation(self.env)` ya en `True` y entran por la rama de
        arriba -que no cascadea a la contraparte-, sin necesidad de
        heurística ninguna en este método.
        """
        if is_propagation(self.env):
            to_void = self.filtered(lambda m: m.picking_id.state == "done")
            if to_void:
                # Review final, Critical 1 (verificado, no supuesto): estas
                # dos escrituras quedan como escrituras NORMALES, sin
                # sudo. Los dos alcances anchos que abren el flag sin sudo
                # -`stock.picking.unlink()` y `_merge_moves()`- no llegan
                # nunca acá con un picking `done` y contraparte (core no
                # deja borrar un picking done, y la fusión ocurre al
                # confirmar, sobre pickings que todavía no lo están): se
                # verificó corriendo la suite entera. Ponerlas en sudo
                # "por las dudas" era peor: dejaba viva por `unlink()` la
                # misma puerta que el Critical 1 cierra en `write()`, o
                # sea anular stock validado de la otra compañía mandando
                # `skip_intercompany_sync` en el contexto por RPC. Sin
                # sudo, el guard las alcanza y ese camino queda cerrado
                # (ver test_context_flag_alone_does_not_bypass_unlink).
                to_void.move_line_ids.write({"quantity": 0.0})
                to_void.write({"product_uom_qty": 0.0})
            to_delete = self - to_void
            return super(StockMove, to_delete).unlink() if to_delete else True

        relevant = self.filtered(
            lambda m: m.picking_id.state in ("done", "cancel")
            or m.picking_id.counterpart_of_picking_id
        )
        if not relevant:
            return super().unlink()

        pairs = [(move, move._get_counterpart_move()) for move in relevant]
        pickings_to_check = self.env["stock.picking"]
        for move, counterpart in pairs:
            if (
                move.picking_id.state in ("done", "cancel")
                and move.picking_id.counterpart_picking_id
            ):
                pickings_to_check |= move.picking_id
            if counterpart and counterpart.picking_id.state in ("done", "cancel"):
                pickings_to_check |= counterpart.picking_id
        if pickings_to_check:
            pickings_to_check._check_intercompany_edit_allowed()

        to_void = relevant.filtered(lambda m: m.picking_id.state == "done")
        if to_void:
            to_void.action_intercompany_void()

        to_delete = relevant - to_void
        counterparts = self.env["stock.move"]
        for move, counterpart in pairs:
            if move not in to_delete:
                continue
            own_body = _(
                "Línea eliminada: %(product)s",
                product=move.product_id.display_name,
            )
            post_sync_note(move.picking_id, own_body)
            if not counterpart:
                continue
            counterparts |= counterpart
            if not counterpart.picking_id:
                continue
            counter_verb = (
                _("anulada")
                if counterpart.picking_id.state == "done"
                else _("eliminada")
            )
            counter_body = _(
                "Línea %(verb)s: %(product)s",
                verb=counter_verb,
                product=move.product_id.display_name,
            )
            post_sync_note(
                counterpart.picking_id, counter_body, source_picking=move.picking_id
            )

        res = super(StockMove, self - to_void).unlink()
        if counterparts:
            as_propagation(counterparts).unlink()
        return res
