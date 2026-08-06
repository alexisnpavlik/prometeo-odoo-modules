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

    counterpart_of_move_id = fields.Many2one("stock.move", check_company=False)

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
                        "%(product)s usa lote o número de serie: hay que "
                        "indicar el lote (línea con lot_id/lot_name) al "
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
            if changed:
                as_propagation(counterpart).write(changed)
        return res
