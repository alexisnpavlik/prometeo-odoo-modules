# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .intercompany_sync import get_counterpart, is_propagation

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

    def write(self, vals):
        """Corta la edición de validados que no cumpla el rol."""
        if any(field in vals for field in GUARDED_PICKING_FIELDS):
            self._check_intercompany_edit_allowed()
        return super().write(vals)

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
            picking.move_ids.filtered(
                lambda m: m.state == "draft"
            )._action_confirm(merge=False)
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
        counterparts = []
        for picking in self:
            if picking.location_dest_id.usage in ("customer", "transit"):
                counterpart = picking._create_counterpart_picking()
                counterparts.append((picking, counterpart))
        res = super()._action_done()
        for picking, counterpart in counterparts:
            picking._finalize_counterpart_picking(counterpart)
        return res

    def _finalize_counterpart_picking(self, counterpart_picking):
        """hook to finalize required steps on the counterpart picking after the initial
        outgoing picking is done"""
