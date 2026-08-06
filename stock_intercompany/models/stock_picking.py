# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .intercompany_sync import (
    as_propagation,
    get_counterpart,
    is_propagation,
    post_sync_note,
)

# Campos cuya escritura sobre un picking validado exige el rol de manager.
#
# "priority" queda deliberadamente afuera: es cosmético (no cambia el
# contenido efectivo del picking) y el propio _action_done() de Odoo lo
# resetea a '0' al validar (stock/models/stock_picking.py, self.write({
# 'date_done': ..., 'priority': '0'})), ya con el picking en state "done"
# y el espejo ya creado. Vigilarlo rompía la validación de cualquier
# entrega intercompany. La Tarea 6 lo sincroniza igual con la contraparte:
# "vigilado" y "sincronizado" son listas distintas.
GUARDED_PICKING_FIELDS = (
    "scheduled_date",
    "move_ids",
    "move_ids_without_package",
    "move_line_ids",
)

# Campos de cabecera que viajan al espejo cuando cambian de verdad.
# Lista distinta de GUARDED_PICKING_FIELDS: "vigilado" (exige el rol para
# editar un validado) y "sincronizado" (se propaga a la contraparte) son
# conceptos independientes. "priority" está sincronizado aunque no esté
# vigilado (ver el comentario junto a GUARDED_PICKING_FIELDS).
SYNCED_PICKING_FIELDS = ("scheduled_date", "priority")

# Estados en los que el propio Odoo core, fuera de este módulo, no permite
# escribir el campo directamente. "scheduled_date" tiene un inverse
# (`_set_scheduled_date`, stock/models/stock_picking.py líneas 900-903) que
# bloquea INCONDICIONALMENTE cualquier escritura sobre un picking done o
# cancel -sin importar el rol de quien escribe-, porque el campo pasa a
# significar "fecha real del movimiento" una vez procesado (ver
# stock.move.date). Relajar ese bloqueo (como hacía la primera versión de
# esta tarea) reescribe en silencio la fecha real de moves ya hechos, en
# las dos compañías: se descartó ese camino, así que acá solo se evita
# INTENTAR la escritura hacia un espejo que ya está done/cancel, en vez de
# relajar nada. "priority" no tiene ningún estado bloqueado: el propio
# Odoo permite reescribirlo en cualquier estado.
SYNC_BLOCKED_STATES = {
    "scheduled_date": ("done", "cancel"),
}


def _header_field_changed(field, new_value, old_value):
    """Compara el valor viejo y nuevo de un campo de cabecera sincronizado.

    Normaliza `False` y `'0'` como el mismo valor para "priority": es un
    Selection con default `'0'`, así que nunca debería tener `False` como
    valor real, pero una lectura intermedia puede devolver `False` donde
    el valor vigente es la clave por defecto. Sin esto, esa diferencia
    espuria dispara una propagación de `False` hacia el espejo.
    """
    if field == "priority":
        new_value = new_value or "0"
        old_value = old_value or "0"
    return new_value != old_value


def _format_header_value(picking, field, value):
    """Formatea un valor de cabecera para la nota de auditoría del sync.

    Sin esto, la nota mostraba el código crudo del Selection ('0'/'1' en
    vez de la etiqueta traducida) y el Datetime en UTC naive en vez del
    huso horario del usuario que lee la nota.
    """
    field_def = picking._fields[field]
    if field_def.type == "selection":
        selection = dict(picking.fields_get([field])[field].get("selection") or [])
        return selection.get(value, value)
    if field_def.type == "datetime" and value:
        return fields.Datetime.context_timestamp(picking, value).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    return value


class StockPicking(models.Model):
    _inherit = "stock.picking"

    counterpart_of_picking_id = fields.Many2one("stock.picking", check_company=False)
    counterpart_picking_id = fields.Many2one(
        "stock.picking",
        string="Contraparte intercompany",
        compute="_compute_counterpart_picking_id",
        check_company=False,
    )
    can_edit_done = fields.Boolean(
        string="Puede editar validado",
        compute="_compute_can_edit_done",
        help="Verdadero si el usuario es manager intercompany y tiene "
        "habilitadas las dos compañías del espejo.",
    )
    has_counterpart_picking = fields.Boolean(
        string="Tiene contraparte intercompany",
        compute="_compute_has_counterpart_picking",
        help="Espejo booleano de counterpart_picking_id para usar en la vista "
        "sin exponer el Many2one.",
    )

    @api.depends("counterpart_of_picking_id")
    def _compute_counterpart_picking_id(self):
        """Resuelve el espejo en los dos sentidos: hacia el origen y hacia la copia."""
        for picking in self:
            picking.counterpart_picking_id = get_counterpart(
                picking, "counterpart_of_picking_id"
            )

    @api.depends("counterpart_picking_id")
    def _compute_has_counterpart_picking(self):
        """Truthiness de counterpart_picking_id, segura de exponer en la vista.

        counterpart_picking_id resuelve el id de la contraparte con sudo()
        internamente (ver get_counterpart), pero el Many2one que devuelve
        queda atado al env del usuario en curso. Acceder a su display_name
        por ORM directo (`picking.counterpart_picking_id.display_name`) SÍ
        pasa por la ir.rule de stock.picking sin sudo, y revienta con
        AccessError si la compañía de la contraparte no está activa en el
        selector del usuario (comprobado con un test de regresión).

        Por la vía real que usa el formulario web —`web_read()`, en
        `web/models/models.py` de este build— la resolución de
        display_name de un Many2one queda envuelta en `sudo()` (ver el
        código: `for rec in co_records.sudo(): ...`), así que hoy,
        concretamente, NO revienta por ese camino. Pero es un detalle
        interno de esa implementación, no documentado como comportamiento
        garantizado de la API, y no cubre otras superficies (reportes,
        otras vistas, XML-RPC, autocomplete). Por eso este booleano en vez
        de confiar en ese detalle: `bool()` sobre un recordset solo mira si
        hay ids cacheados, no dispara ninguna lectura de campos ni pasa por
        la ir.rule bajo ningún camino, así que la vista puede usarlo para
        decidir si mostrar el botón "Contraparte" sin depender de un
        detalle interno que podría cambiar.
        """
        for picking in self:
            picking.has_counterpart_picking = bool(picking.counterpart_picking_id)

    @api.depends("counterpart_picking_id", "company_id")
    @api.depends_context("uid")
    def _compute_can_edit_done(self):
        """Gobierna el readonly de la vista y respalda el guard del modelo.

        `counterpart.sudo()`: el espejo vive en la otra compañía. La
        ir.rule core de stock.picking restringe la lectura a
        `company_id in env.companies` (las compañías activas en el
        selector, no necesariamente todas las `company_ids` habilitadas
        del usuario). Sin sudo, leer `counterpart.company_id` tira
        AccessError apenas la caché está fría, y el compute reventaría en
        vez de simplemente devolver False.
        """
        is_manager = self.env.user.has_group(
            "stock_intercompany.group_intercompany_manager"
        )
        allowed = self.env.user.company_ids
        for picking in self:
            counterpart = picking.counterpart_picking_id
            picking.can_edit_done = bool(
                is_manager
                and counterpart
                and picking.company_id in allowed
                and counterpart.sudo().company_id in allowed
            )

    def _check_intercompany_edit_allowed(self):
        """Bloquea la edición de un picking intercompany validado sin el rol.

        No aplica a las escrituras propagadas: esas ya vienen en sudo desde la
        contraparte, y son las que permiten que el operador destino reciba de
        menos sin necesitar el rol.
        """
        if is_propagation(self.env):
            return
        for picking in self:
            if picking.state != "done" or not picking.counterpart_picking_id:
                continue
            if picking.can_edit_done:
                continue
            if not self.env.user.has_group(
                "stock_intercompany.group_intercompany_manager"
            ):
                raise AccessError(
                    _(
                        "La transferencia %(name)s ya está validada. Editarla "
                        "requiere el rol «Intercompany: editar transferencias "
                        "validadas».",
                        name=picking.name,
                    )
                )
            raise AccessError(
                _(
                    "Para editar la transferencia validada %(name)s necesitás "
                    "tener habilitadas las dos compañías: %(a)s y %(b)s.",
                    name=picking.name,
                    a=picking.company_id.name,
                    b=picking.counterpart_picking_id.sudo().company_id.name,
                )
            )

    def button_validate(self):
        """La recepción espejo no genera backorder: la diferencia ajusta la entrega.

        Si generara backorder, quedarían dos recepciones para una sola
        entrega y se rompería el vínculo 1 a 1 que es el objetivo del
        módulo -la diferencia entre lo demandado y lo recibido queda
        reflejada propagando la cantidad hacia la entrega (ver
        SYNCED_LINE_FIELDS en stock_move_line.py), no generando un segundo
        picking. La supresión alcanza solo a los pickings que SON un
        espejo (`counterpart_of_picking_id` propio, no el computado
        `counterpart_picking_id`: ver el comentario de `_action_done` más
        abajo sobre por qué la distinción importa acá): un picking sin
        espejo (`mirrors` vacío) sigue el comportamiento original de Odoo
        sin cambios.

        Ronda de corrección 1, Important 3: el contexto de supresión NO se
        aplica nunca a `self` entero. Antes, un batch mixto (espejo +
        picking sin contraparte validados juntos) heredaba
        `skip_backorder=True` en los DOS, porque el contexto se pisaba
        sobre todo el recordset: `_pre_action_done_hook()` (core) no corre
        `_check_backorder()` para NINGÚN picking del batch con ese flag,
        así que el picking sin espejo perdía en silencio su wizard
        "¿crear backorder?" y terminaba con un backorder creado sin
        preguntarle a nadie -medido: `MIXED res=True ... backorders=[...]`
        sobre el picking suelto-. Ahora cada subconjunto se valida por
        separado: primero los espejos (nunca muestran wizard, se
        resuelven solos), después el resto con el comportamiento original
        intacto. No es un caso hipotético: hay dos caminos reales de batch
        en este build - la acción de servidor de la vista lista
        (`stock.action_validate_picking`, `binding_view_types=list`,
        stock/views/stock_picking_views.xml) y
        `stock.picking.batch.action_done()`
        (stock_picking_batch/models/stock_picking_batch.py).
        """
        mirrors = self.filtered(lambda p: p.counterpart_of_picking_id)
        others = self - mirrors
        if not mirrors:
            return super().button_validate()
        mirrors_res = super(
            StockPicking,
            mirrors.with_context(
                skip_backorder=True,
                picking_ids_not_to_backorder=mirrors.ids,
            ),
        ).button_validate()
        if not others:
            return mirrors_res
        others_res = super(StockPicking, others).button_validate()
        return others_res if isinstance(others_res, dict) else mirrors_res

    def write(self, vals):
        """Corta la edición de validados sin rol y propaga la cabecera al espejo.

        Si la escritura ya viene propagada desde la contraparte
        (`is_propagation`), se aplica y se corta ahí: no hay que volver a
        comparar ni a propagar, porque eso es exactamente el eco que
        `skip_intercompany_sync` existe para cortar en un solo salto.

        El estado previo de los campos sincronizados solo se lee cuando
        `vals` toca alguno de ellos: de lo contrario, cualquier escritura
        de la base (toque o no un campo de cabecera) forzaría una lectura
        extra de `scheduled_date`/`priority` sobre cada picking del batch.
        """
        if any(field in vals for field in GUARDED_PICKING_FIELDS):
            self._check_intercompany_edit_allowed()
        if is_propagation(self.env):
            return super().write(vals)
        touches_synced_fields = bool(set(vals) & set(SYNCED_PICKING_FIELDS))
        previous = {}
        if touches_synced_fields:
            previous = {
                picking.id: {
                    field: picking[field] for field in SYNCED_PICKING_FIELDS
                }
                for picking in self
            }
        res = super().write(vals)
        if touches_synced_fields:
            self._propagate_picking_changes(previous)
        return res

    def _propagate_picking_changes(self, previous):
        """Lleva al espejo los campos de cabecera que efectivamente cambiaron.

        Tres cortes antes de propagar algo:

        - Un picking origen ya `done`/`cancel` no propaga nada. Es el
          mismo caso que `_action_done()` de Odoo, que escribe
          `date_done`/`priority` sobre el picking DESPUÉS de que ya quedó
          `done` y el espejo ya existe (ver el comentario junto a
          `GUARDED_PICKING_FIELDS`): sin este corte, esa escritura interna
          del propio flujo de validación se propagaba como si fuera una
          edición real, dejando notas espurias en las dos puntas. Como
          consecuencia, y es una limitación real, no una elegida: como el
          espejo solo existe una vez que la entrega ya está validada, la
          entrega SIEMPRE está done en cuanto tiene contraparte, así que
          la única dirección viva para propagar cabecera es recepción →
          entrega.
        - Si la contraparte también está en `self` (p. ej.
          `(delivery | reception).write(...)` tocando las dos puntas de
          una), no se propaga: el propio `super().write()` del batch ya
          dejó el valor en las dos, y propagar además duplicaría la
          escritura y el chatter.
        - Por campo, si el estado de la contraparte está en
          `SYNC_BLOCKED_STATES` para ese campo (hoy, `scheduled_date`
          hacia un espejo `done`/`cancel`), no se intenta: escribirlo
          reventaría con el `UserError` incondicional del core.
        """
        for picking in self:
            if picking.state in ("done", "cancel"):
                continue
            counterpart = picking.counterpart_picking_id
            if not counterpart or counterpart in self:
                continue
            old = previous.get(picking.id, {})
            changed = {}
            for field in SYNCED_PICKING_FIELDS:
                if field not in old:
                    continue
                new_value = picking[field]
                if not _header_field_changed(field, new_value, old[field]):
                    continue
                if counterpart.state in SYNC_BLOCKED_STATES.get(field, ()):
                    continue
                changed[field] = new_value
            if not changed:
                continue
            as_propagation(counterpart).write(changed)
            for field, value in changed.items():
                label = picking.fields_get([field])[field]["string"]
                body = _(
                    "%(label)s: %(old)s → %(new)s",
                    label=label,
                    old=_format_header_value(picking, field, old[field]),
                    new=_format_header_value(picking, field, value),
                )
                post_sync_note(picking, body)
                post_sync_note(counterpart, body, source_picking=picking)

    def action_open_counterpart_picking(self):
        """Abre el picking espejo en la otra compañía.

        `counterpart.sudo().company_id`: misma razón que en can_edit_done.
        El espejo vive en una compañía que el usuario puede tener habilitada
        pero no activa en el selector; sin sudo, leer su company_id acá
        (para poder armar el contexto que activa esa compañía) revienta con
        AccessError antes de llegar a abrir nada.

        Si el usuario directamente NO tiene esa compañía en su
        `company_ids` (nunca habilitada, no solo "no activa ahora"), armar
        igual un contexto con `allowed_company_ids` apuntando a ella no
        sirve de nada: el propio `Environment.companies` de Odoo valida que
        las compañías activas sean un subconjunto de las habilitadas del
        usuario, y el primer `read` que dispare el cliente web contra el
        formulario destino revienta con un AccessError crudo ("Acceso a
        empresas sin autorización o que no son válidas") — el mismo caso
        que ya rompió la Tarea 4. Se valida acá antes, con un UserError
        explícito que dice qué compañía falta.
        """
        self.ensure_one()
        counterpart = self.counterpart_picking_id
        if not counterpart:
            raise UserError(
                _(
                    "La transferencia %(name)s no tiene contraparte intercompany.",
                    name=self.name,
                )
            )
        counterpart_company = counterpart.sudo().company_id
        if counterpart_company not in self.env.user.company_ids:
            raise UserError(
                _(
                    "No tenés habilitada la compañía %(company)s, donde está "
                    "la contraparte de %(name)s. Pedile a un administrador "
                    "que te la habilite.",
                    company=counterpart_company.name,
                    name=self.name,
                )
            )
        # Se arranca de un contexto sin los "default_*" del origen: si el
        # usuario llegó desde una acción con, por ejemplo,
        # default_picking_type_id de ESTA compañía, arrastrarlo al
        # formulario de la contraparte (activada vía allowed_company_ids)
        # puede chocar con un mismatch de compañía en cuanto el usuario
        # intente crear algo nuevo desde ahí.
        clean_context = {
            key: value
            for key, value in self.env.context.items()
            if not key.startswith("default_")
        }
        clean_context["allowed_company_ids"] = [counterpart_company.id]
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": counterpart.id,
            "view_mode": "form",
            "context": clean_context,
        }

    def _create_counterpart_picking(self):
        companies = self.env["res.company"].sudo().search([])
        partners = {cp.partner_id: cp for cp in companies}
        picking = self.env["stock.picking"]
        if self.partner_id in partners:
            company = partners[self.partner_id]
            # Switch to target company context before creating picking
            picking_model = self.env["stock.picking"].sudo().with_company(company)
            vals = self._get_counterpart_picking_vals(company)
            # Create picking in correct company context
            picking = picking_model.create(vals)
            # El compute de counterpart_picking_id depende de
            # counterpart_of_picking_id, campo que solo llena el espejo
            # apuntando a self: depends() no puede rastrear la búsqueda
            # inversa que hace get_counterpart(). Si algo leyó
            # self.counterpart_picking_id antes de este create (p. ej. un
            # guard en action_confirm/button_validate), quedó cacheado
            # vacío y no se refresca solo. Se invalida a mano apenas existe
            # el espejo para que cualquier lectura posterior de self lo
            # recalcule. can_edit_done va en la misma lista: depende de
            # counterpart_picking_id, pero _invalidate_cache solo mete en
            # el spec los campos pedidos y sus inversos, no sus
            # dependientes computados — si no lo invalidamos a mano acá
            # también, queda en caché con el valor rancio de antes del
            # espejo (False), y el guard de create/unlink de la Tarea 8
            # se lo va a comer y bloquear a un manager legítimo.
            self.invalidate_recordset(["counterpart_picking_id", "can_edit_done"])
            # "picking_id" en stock.move.line es un campo propio (no
            # derivado de move_id), así que no se completa solo al crear
            # las líneas anidadas dentro de move_ids: hay que sincronizarlo
            # a mano para que picking.move_line_ids las vea.
            picking.move_ids.move_line_ids.picking_id = picking.id
            # Confirm picking in the same company context. merge=False:
            # el merge automático de moves de Odoo colapsaría dos moves
            # espejo del mismo producto en uno solo, perdiendo la relación
            # 1 a 1 con counterpart_of_move_id que este módulo necesita.
            #
            # with_context(skip_intercompany_sync=True): _action_confirm()
            # dispara _action_assign(), que reserva stock en la ubicación
            # proveedor (virtual, siempre disponible) escribiendo
            # `quantity` sobre la línea del espejo RECIÉN CREADA -no es una
            # edición real de nadie, es el bootstrap interno de la
            # reserva-. Sin este flag, esa escritura interna se veía como
            # un cambio genuino de "cantidad hecha" y se propagaba de
            # vuelta hacia la línea de origen, pisando en silencio la
            # cantidad parcial que el operador ya había cargado ANTES de
            # validar (p. ej. 9 de 10): la demanda plena de la reserva
            # (10) volvía a escribirse sobre el origen, y la recepción
            # parcial dejaba de generar la diferencia real. Encontrado
            # verificando explícitamente, contra el fuente de este
            # contenedor (stock/models/stock_move.py, _action_assign:
            # `to_update[0].quantity += ...`), qué escribe core durante la
            # validación -no asumido-. Mismo criterio para el resto del
            # bootstrap: nada de lo que pasa acá (confirmar y reservar el
            # espejo recién creado) es una edición real que deba viajar de
            # vuelta al origen.
            picking.move_ids.filtered(
                lambda m: m.state == "draft"
            ).with_context(skip_intercompany_sync=True)._action_confirm(merge=False)
        return picking

    def _get_counterpart_picking_vals(self, company):
        # Get warehouse and picking type in correct company context
        warehouse = False
        with_company = self.env["stock.warehouse"].sudo().with_company(company)
        ptype = False

        if company.intercompany_in_type_id:
            ptype = company.intercompany_in_type_id
            if ptype.warehouse_id:
                warehouse = ptype.warehouse_id

        if not warehouse:
            warehouse = with_company.search([("company_id", "=", company.id)], limit=1)

        if not ptype:
            ptype = warehouse.in_type_id

        # Ensure locations belong to correct company
        location_dest = ptype.default_location_dest_id or warehouse.lot_stock_id
        supplier_location = self.env.ref("stock.stock_location_suppliers")

        move_ids = self._get_counterpart_move_commands(company, ptype)

        return {
            "partner_id": self.company_id.partner_id.id,
            "company_id": company.id,
            "origin": self.name,
            "picking_type_id": ptype.id,
            "state": "draft",
            "location_id": supplier_location.id,
            "location_dest_id": location_dest.id,
            "counterpart_of_picking_id": self.id,
            "move_ids": move_ids,
            "scheduled_date": self.scheduled_date,
            "priority": self.priority,
        }

    def _get_counterpart_move_commands(self, company, picking_type):
        """Construye los moves espejo con sus líneas anidadas dentro de cada move.

        Ojo si reutilizás esto para crear líneas nueva: las líneas quedan
        con ``picking_id=False`` a propósito, porque el ORM solo completa
        el inverso del o2m que se está anidando (``move_id``, vía
        ``move_line_ids`` del move) y ``picking_id`` en
        ``stock.move.line`` es un campo propio, no derivado de
        ``move_id``. Quien use estos commands para crear registros tiene
        que sincronizar ``picking_id`` a mano después (como hace
        ``_create_counterpart_picking`` con
        ``picking.move_ids.move_line_ids.picking_id = picking.id``), o
        las líneas quedan invisibles en ``picking.move_line_ids``.
        """
        supplier_location = self.env.ref("stock.stock_location_suppliers")
        if supplier_location.company_id:
            supplier_location.sudo().company_id = False

        location_dest = picking_type.default_location_dest_id
        if not location_dest:
            warehouse = (
                self.env["stock.warehouse"]
                .sudo()
                .search([("company_id", "=", company.id)], limit=1)
            )
            location_dest = warehouse.lot_stock_id

        common_vals = {
            "company_id": company.id,
            "location_id": supplier_location.id,
            "location_dest_id": location_dest.id,
            "picking_type_id": picking_type.id,
        }

        move_commands = []
        for move in self.move_ids.sudo():
            line_commands = []
            for line in move.move_line_ids:
                line_vals = line.with_company(company).copy_data(
                    dict(
                        common_vals,
                        move_id=False,
                        picking_id=False,
                        counterpart_of_line_id=line.id,
                    )
                )[0]
                line_commands.append(Command.create(line_vals))
            move_vals = move.with_company(company).copy_data(
                dict(
                    common_vals,
                    counterpart_of_move_id=move.id,
                    move_line_ids=line_commands,
                )
            )[0]
            move_commands.append(Command.create(move_vals))
        return move_commands

    def _action_done(self):
        """Crea el espejo de las entregas y fuerza `cancel_backorder` en las recepciones espejo.

        Ronda de corrección 1, Critical 2: `button_validate()` (más arriba)
        suprime el wizard y arma `picking_ids_not_to_backorder`, pero core
        (stock/models/stock_picking.py) filtra esa lista con
        `lambda p: p.picking_type_id.create_backorder != 'always'` antes de
        decidir con qué `cancel_backorder` llamar a `_action_done()`. Si el
        tipo de operación de recepción de la compañía destino está
        configurado en "Always" -un valor soportado de fábrica-, el espejo
        se cae de esa lista, entra con `cancel_backorder=False` y genera
        backorder igual: dos recepciones para una entrega, medido
        (`ALWAYS2 state=done bo=['Sync /IN/00002']`), exactamente el
        invariante que este módulo existe para sostener.

        La única vía que no depende de `picking_ids_not_to_backorder` es
        forzar `cancel_backorder=True` directamente en el contexto con el
        que se llama a `_action_done()`, que es lo que de verdad decide
        (stock/models/stock_move.py: `_create_backorder()` y
        `_create_backorder()` a nivel picking corren solo `if not
        cancel_backorder`) si se genera el split y el backorder,
        sin importar qué política tenga configurada el tipo de operación.

        `counterpart_of_picking_id` (campo propio, no el `counterpart_picking_id`
        computado) identifica de forma inequívoca a una recepción espejo:
        se completa SOLO al crear el espejo (ver
        `_get_counterpart_picking_vals`) y nunca en la entrega origen. Usar
        el computado acá sería un error distinto: apenas este método crea
        el espejo de una entrega (más abajo) e invalida la caché,
        `counterpart_picking_id` de esa MISMA entrega origen empieza a
        resolver al espejo recién creado, así que un filtro por el
        computado capturaría también a la entrega origen -que si necesita
        poder generar backorder normalmente, ver
        test_operator_creates_backorder_without_role-.
        """
        counterparts = []
        for picking in self:
            if picking.location_dest_id.usage in ("customer", "transit"):
                counterpart = picking._create_counterpart_picking()
                counterparts.append((picking, counterpart))
        mirrors = self.filtered(lambda p: p.counterpart_of_picking_id)
        others = self - mirrors
        res = True
        if mirrors:
            res = super(
                StockPicking, mirrors.with_context(cancel_backorder=True)
            )._action_done()
        if others:
            res = super(StockPicking, others)._action_done() and res
        for picking, counterpart in counterparts:
            picking._finalize_counterpart_picking(counterpart)
        return res

    def _finalize_counterpart_picking(self, counterpart_picking):
        """hook to finalize required steps on the counterpart picking after the initial
        outgoing picking is done"""
