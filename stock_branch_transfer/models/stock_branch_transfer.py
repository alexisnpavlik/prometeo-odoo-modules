import logging
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)

# Campos cuyo cambio en un traslado ya enviado mueve stock
STOCK_FIELDS = {"company_id", "dest_company_id", "line_ids"}

STATES = [
    ("draft", "Borrador"),
    ("in_transit", "En camino"),
    ("received", "Recibido"),
    ("with_diff", "Con diferencias"),
    ("closed", "Cerrado"),
    ("cancel", "Anulado"),
]


class StockBranchTransfer(models.Model):
    _name = "stock.branch.transfer"
    _description = "Traslado entre sucursales"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(string="Número", default="Nuevo", readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", string="Origen", required=True, default=lambda self: self.env.company, tracking=True
    )
    dest_company_id = fields.Many2one("res.company", string="Destino", required=True, tracking=True)
    state = fields.Selection(STATES, string="Estado", default="draft", required=True, copy=False, tracking=True)
    user_id = fields.Many2one("res.users", string="Creado por", default=lambda self: self.env.user, readonly=True)
    date_sent = fields.Datetime(string="Fecha de envío", readonly=True, copy=False)
    date_received = fields.Datetime(string="Fecha de recepción", readonly=True, copy=False)
    diff_note = fields.Text(string="Nota de diferencias", copy=False)
    line_ids = fields.One2many("stock.branch.transfer.line", "transfer_id", string="Productos", copy=True)
    picking_ids = fields.One2many("stock.picking", "branch_transfer_id", string="Movimientos", readonly=True)
    is_manager = fields.Boolean(compute="_compute_is_manager")
    is_origin_mine = fields.Boolean(
        string="Enviado por mis sucursales", compute="_compute_is_mine", search="_search_is_origin_mine"
    )
    is_dest_mine = fields.Boolean(
        string="Destino en mis sucursales", compute="_compute_is_mine", search="_search_is_dest_mine"
    )

    def _compute_is_manager(self):
        """Habilita en la vista la edición posterior al envío."""
        self.is_manager = self._is_manager()

    def _compute_is_mine(self):
        """Origen/destino dentro de las sucursales del usuario."""
        companies = self.env.user.company_ids
        for transfer in self:
            transfer.is_origin_mine = transfer.company_id in companies
            transfer.is_dest_mine = transfer.dest_company_id in companies

    def _search_is_origin_mine(self, operator, value):
        """Dominio de "Enviados"."""
        return self._search_mine("company_id", operator, value)

    def _search_is_dest_mine(self, operator, value):
        """Dominio de "Por recibir"."""
        return self._search_mine("dest_company_id", operator, value)

    def _search_mine(self, field, operator, value):
        """Dominio por empresa contra las sucursales del usuario."""
        positive = (operator == "=") == bool(value)
        return [(field, "in" if positive else "not in", self.env.user.company_ids.ids)]

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna el número de secuencia TRS/ al crear."""
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code("stock.branch.transfer") or "Nuevo"
        return super().create(vals_list)

    def write(self, vals):
        """Editar un traslado ya enviado es cosa de managers y corrige el stock."""
        if self.env.context.get("branch_transfer_internal") or not STOCK_FIELDS & set(vals):
            return super().write(vals)
        sent = self.filtered(lambda t: t.state != "draft")
        if not sent:
            return super().write(vals)
        sent._check_manager_edit()
        # Las líneas tocadas por esta escritura no reconcilian por su cuenta: se hace una vez acá.
        res = super(StockBranchTransfer, self.with_context(branch_transfer_internal=True)).write(vals)
        sent._reconcile_stock()
        sent._log_manager_edit()
        return res

    def unlink(self):
        """Solo se borran borradores; lo enviado se anula."""
        if any(transfer.state != "draft" for transfer in self):
            raise UserError(_("Usá Anular para revertir un traslado ya enviado."))
        return super().unlink()

    @api.constrains("company_id", "dest_company_id")
    def _check_dest_company(self):
        """El destino tiene que ser otra sucursal."""
        for transfer in self:
            if transfer.company_id == transfer.dest_company_id:
                raise ValidationError(_("La sucursal destino tiene que ser distinta de la de origen."))

    # ------------------------------------------------------------------
    # Helpers de permisos y estado
    # ------------------------------------------------------------------

    def _is_manager(self):
        """True si el usuario actual es manager de traslados."""
        return self.env.user.has_group("stock_branch_transfer.group_branch_transfer_manager")

    def _check_state(self, *states):
        """Lanza UserError si algún traslado no está en los estados indicados."""
        labels = dict(STATES)
        for transfer in self:
            if transfer.state not in states:
                raise UserError(_(
                    "El traslado %(name)s está en estado \"%(state)s\" y no admite esta acción.",
                    name=transfer.name,
                    state=labels[transfer.state],
                ))

    def _check_manager(self):
        """Solo un manager puede seguir."""
        if not self._is_manager():
            raise UserError(_("Solo un manager de traslados puede hacer esto."))

    def _check_company_access(self, company):
        """El usuario tiene que tener acceso a la sucursal (o ser manager)."""
        if company not in self.env.user.company_ids and not self._is_manager():
            raise UserError(_("No tenés acceso a la sucursal %s.", company.name))

    def _check_manager_edit(self):
        """Un traslado ya enviado solo lo edita un manager."""
        if not self._is_manager():
            raise UserError(_("Solo un manager puede editar un traslado ya enviado."))

    def _log_manager_edit(self):
        """Deja constancia en el chatter de la edición posterior al envío."""
        for transfer in self:
            lines = "<br/>".join(
                _("%(product)s: enviado %(sent)s, recibido %(received)s",
                  product=line.product_id.display_name, sent=line.qty_sent, received=line.qty_received)
                for line in transfer.line_ids
            )
            transfer.message_post(body=_("Editado por %s; stock corregido.", self.env.user.name) + "<br/>" + lines)

    def _before_line_change(self, context):
        """Valida permisos antes de tocar líneas de traslados ya enviados."""
        if not context.get("branch_transfer_internal"):
            sent = self.filtered(lambda t: t.state != "draft")
            if sent:
                sent._check_manager_edit()

    def _after_line_change(self, context, checked=False):
        """Tras tocar líneas de traslados ya enviados: permisos, stock y chatter."""
        if context.get("branch_transfer_internal"):
            return
        sent = self.filtered(lambda t: t.state != "draft")
        if not sent:
            return
        if not checked:
            sent._check_manager_edit()
        sent._reconcile_stock()
        sent._log_manager_edit()

    def _write_internal(self, vals):
        """Escritura hecha por las acciones del flujo (no cuenta como edición manual)."""
        return self.with_context(branch_transfer_internal=True).write(vals)

    # ------------------------------------------------------------------
    # Motor de stock: objetivo por ubicación + reconciliación
    # ------------------------------------------------------------------

    @api.model
    def _stock_location(self, company):
        """Ubicación de stock del (único) almacén de la empresa."""
        warehouse = self.env["stock.warehouse"].sudo().search([("company_id", "=", company.id)], limit=1)
        if not warehouse:
            raise UserError(_("La sucursal %s no tiene almacén.", company.name))
        return warehouse.lot_stock_id

    def _transit_location(self):
        """Ubicación de tránsito propia del módulo."""
        return self.env.ref("stock_branch_transfer.location_branch_transit")

    def _target_quantities(self):
        """Neto que el traslado debería haber movido, por (producto, ubicación).

        draft/cancel: nada. in_transit: origen -s, tránsito +s.
        with_diff: origen -max(s, r), tránsito max(s, r) - r, destino +r.
        received/closed: origen -r, destino +r.
        """
        self.ensure_one()
        target = defaultdict(float)
        if self.state in ("draft", "cancel"):
            return target
        origin = self._stock_location(self.company_id).id
        transit = self._transit_location().id
        dest = self._stock_location(self.dest_company_id).id
        sent, received = defaultdict(float), defaultdict(float)
        for line in self.line_ids:
            sent[line.product_id.id] += line.qty_sent
            received[line.product_id.id] += line.qty_received
        for product_id in set(sent) | set(received):
            s, r = sent[product_id], received[product_id]
            if self.state == "in_transit":
                target[(product_id, origin)] -= s
                target[(product_id, transit)] += s
            elif self.state == "with_diff":
                out = max(s, r)
                target[(product_id, origin)] -= out
                target[(product_id, transit)] += out - r
                target[(product_id, dest)] += r
            else:
                target[(product_id, origin)] -= r
                target[(product_id, dest)] += r
        return target

    def _current_quantities(self):
        """Neto ya movido por los pickings hechos del traslado, por (producto, ubicación)."""
        self.ensure_one()
        current = defaultdict(float)
        moves = self.sudo().picking_ids.move_ids.filtered(lambda m: m.state == "done")
        for move in moves:
            current[(move.product_id.id, move.location_dest_id.id)] += move.quantity
            current[(move.product_id.id, move.location_id.id)] -= move.quantity
        return current

    def _reconcile_stock(self):
        """Genera y valida los pickings que llevan el stock al objetivo del traslado.

        Todo pasa por tránsito: una ubicación con faltante recibe desde tránsito,
        una con sobrante devuelve a tránsito. Tránsito queda balanceado solo.
        """
        transit = self._transit_location()
        Product = self.env["product.product"].sudo()
        Location = self.env["stock.location"].sudo()
        for transfer in self:
            target = transfer._target_quantities()
            current = transfer._current_quantities()
            grouped = defaultdict(list)
            for key in set(target) | set(current):
                product_id, location_id = key
                if location_id == transit.id:
                    continue
                product = Product.browse(product_id)
                delta = target[key] - current[key]
                if float_is_zero(delta, precision_rounding=product.uom_id.rounding):
                    continue
                direction = "in" if delta > 0 else "out"
                grouped[(location_id, direction)].append((product, abs(delta)))
            for (location_id, direction), items in grouped.items():
                transfer._create_done_picking(Location.browse(location_id), direction, items)

    def _create_done_picking(self, location, direction, items):
        """Crea un picking validado entre la ubicación y tránsito (sin contacto)."""
        self.ensure_one()
        company = location.company_id
        transit = self._transit_location()
        warehouse = self.env["stock.warehouse"].sudo().search([("company_id", "=", company.id)], limit=1)
        if direction == "out":
            picking_type, src, dst = warehouse.out_type_id, location, transit
        else:
            picking_type, src, dst = warehouse.in_type_id, transit, location
        picking = self.env["stock.picking"].sudo().with_company(company).create({
            "picking_type_id": picking_type.id,
            "location_id": src.id,
            "location_dest_id": dst.id,
            "company_id": company.id,
            "partner_id": False,
            "origin": self.name,
            "branch_transfer_id": self.id,
            "move_ids": [(0, 0, {
                "name": self.name,
                "product_id": product.id,
                "product_uom": product.uom_id.id,
                "product_uom_qty": qty,
                "location_id": src.id,
                "location_dest_id": dst.id,
                "company_id": company.id,
            }) for product, qty in items],
        })
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking._action_done()
        return picking

    # ------------------------------------------------------------------
    # Acciones del flujo
    # ------------------------------------------------------------------

    def action_send(self):
        """Borrador → En camino: sale el stock del origen hacia tránsito."""
        self._check_state("draft")
        for transfer in self:
            transfer._check_company_access(transfer.company_id)
            if not any(line.qty_sent > 0 for line in transfer.line_ids):
                raise UserError(_("Cargá al menos un producto con cantidad a enviar."))
            transfer._write_internal({"state": "in_transit", "date_sent": fields.Datetime.now()})
        self._reconcile_stock()
        return True

    def action_receive(self):
        """En camino → Recibido: entra al destino todo lo enviado."""
        self._check_state("in_transit")
        for transfer in self:
            transfer._check_company_access(transfer.dest_company_id)
            for line in transfer.line_ids:
                line.with_context(branch_transfer_internal=True).qty_received = line.qty_sent
            transfer._write_internal({"state": "received", "date_received": fields.Datetime.now()})
        self._reconcile_stock()
        return True

    def action_open_receive_diff(self):
        """Abre el asistente para recibir con diferencias."""
        self.ensure_one()
        self._check_state("in_transit")
        self._check_company_access(self.dest_company_id)
        return {
            "type": "ir.actions.act_window",
            "name": _("Recibido con diferencias"),
            "res_model": "stock.branch.transfer.receive.diff",
            "view_mode": "form",
            "target": "new",
            "context": {"default_transfer_id": self.id},
        }

    def action_close(self):
        """Con diferencias → Cerrado (manager): el faltante vuelve al origen."""
        self._check_manager()
        self._check_state("with_diff")
        self._write_internal({"state": "closed"})
        self._reconcile_stock()
        return True

    def action_cancel(self):
        """Anular (manager): revierte todo el stock movido y deja el traslado anulado."""
        self._check_manager()
        self._check_state("in_transit", "received", "with_diff", "closed")
        self._write_internal({"state": "cancel"})
        self._reconcile_stock()
        for transfer in self:
            transfer.message_post(body=_("Anulado por %s; stock revertido.", self.env.user.name))
        return True

    @api.model
    def get_pending_count(self):
        """Traslados pendientes para las sucursales del usuario (contador del ícono)."""
        company_ids = self.env.user.company_ids.ids
        return self.sudo().search_count([
            "|",
            "&", ("state", "=", "in_transit"), ("dest_company_id", "in", company_ids),
            "&", ("state", "=", "with_diff"),
            "|", ("company_id", "in", company_ids), ("dest_company_id", "in", company_ids),
        ])
