import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class StockCountSession(models.Model):
    _name = "stock.count.session"
    _description = "Sesión de conteo de stock"
    _order = "date_start desc, id desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("Nuevo"),
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Ubicación",
        required=True,
        domain="[('usage', '=', 'internal'), ('company_id', 'in', [company_id, False])]",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Contado por",
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    state = fields.Selection(
        [("draft", "Borrador"), ("applied", "Aplicado"), ("cancelled", "Cancelado")],
        string="Estado",
        default="draft",
        required=True,
        copy=False,
    )
    date_start = fields.Datetime(
        string="Inicio",
        default=fields.Datetime.now,
        readonly=True,
    )
    date_applied = fields.Datetime(string="Aplicado el", readonly=True, copy=False)
    line_ids = fields.One2many(
        "stock.count.line",
        "session_id",
        string="Líneas",
    )
    line_count = fields.Integer(string="Productos contados", compute="_compute_counts")
    diff_count = fields.Integer(string="Con diferencia", compute="_compute_counts")

    @api.depends("line_ids", "line_ids.difference_qty")
    def _compute_counts(self):
        """Resume cuántas líneas hay y cuántas difieren del stock del sistema."""
        for session in self:
            session.line_count = len(session.line_ids)
            session.diff_count = len(
                session.line_ids.filtered(
                    lambda line: not float_is_zero(
                        line.difference_qty,
                        precision_rounding=line.product_id.uom_id.rounding or 0.01,
                    )
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna la referencia desde la secuencia al crear."""
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "stock.count.session"
                ) or _("Nuevo")
        return super().create(vals_list)

    @api.constrains("company_id", "location_id")
    def _check_location_company(self):
        """Evita mezclar stock de una empresa con la ubicación de otra.

        Una ubicación compartida (company_id vacío) es válida. El chequeo
        cubre el caso de que la sesión se arme por RPC, importación o
        duplicado y termine con una ubicación que no es de su empresa.
        """
        for session in self:
            if (
                session.location_id.company_id
                and session.location_id.company_id != session.company_id
            ):
                raise ValidationError(
                    _(
                        "La ubicación '%s' pertenece a la empresa '%s', "
                        "distinta de la empresa de la sesión ('%s').",
                        session.location_id.display_name,
                        session.location_id.company_id.display_name,
                        session.company_id.display_name,
                    )
                )

    def write(self, vals):
        """Bloquea empresa/ubicación con líneas cargadas, y edición de sesiones aplicadas.

        Una sesión aplicada ya movió stock real: permitir que se edite o
        borre por RPC falsificaría el registro de qué se contó y quién lo
        aplicó.
        """
        locked_fields = {"company_id", "location_id"}
        if locked_fields & set(vals):
            for session in self:
                if session.line_ids:
                    raise UserError(
                        _(
                            "No se puede cambiar la empresa ni la ubicación de "
                            "'%s': ya tiene líneas cargadas. Cancelá la sesión y "
                            "creá una nueva.",
                            session.name,
                        )
                    )
        # Ningún campo es escribible una vez aplicada, ni siquiera 'state' o
        # 'date_applied'. No hace falta whitelist para action_apply(): su
        # propio write ocurre mientras el estado todavía es 'draft', así que
        # nunca entra acá. Dejar 'state' pasar permitiría reabrir la sesión
        # con un write crudo por RPC, esquivando action_reset_to_draft() y
        # habilitando re-aplicar cantidades viejas contra el stock actual;
        # dejar pasar 'date_applied' permitiría falsificar el sello de
        # auditoría.
        for session in self:
            if session.state == "applied":
                raise UserError(
                    _(
                        "No se puede modificar la sesión '%s': ya fue "
                        "aplicada y el registro del conteo no se puede "
                        "alterar. Corregí el conteo con una sesión nueva.",
                        session.name,
                    )
                )
        return super().write(vals)

    def unlink(self):
        """Impide borrar una sesión que no está en borrador.

        Borrar una sesión aplicada dejaría movimientos de stock reales sin
        el registro de auditoría de qué se contó y quién lo aplicó.
        """
        for session in self:
            if session.state != "draft":
                raise UserError(
                    _(
                        "No se puede eliminar la sesión '%s': no está en "
                        "borrador.",
                        session.name,
                    )
                )
        return super().unlink()

    def _check_draft(self):
        """Valida que la sesión esté en borrador antes de modificarla."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(
                _("La sesión '%s' no está en borrador.", self.name)
            )

    def action_cancel(self):
        """Cancela una sesión en borrador."""
        for session in self:
            session._check_draft()
        self.write({"state": "cancelled"})
        return True

    def action_reset_to_draft(self):
        """Devuelve a borrador una sesión cancelada. Las aplicadas no se reabren."""
        for session in self:
            if session.state != "cancelled":
                raise UserError(
                    _(
                        "Solo se pueden reabrir sesiones canceladas. "
                        "Un conteo aplicado se corrige con una sesión nueva."
                    )
                )
        self.write({"state": "draft"})
        return True

    def action_apply(self):
        """Aplica el conteo como ajuste de inventario nativo, línea por línea.

        Cada línea corre en su propio savepoint que envuelve tanto la
        preparación del quant (_apply_line) como la aplicación contable
        (action_apply_inventory): esta última es la parte que realmente
        puede fallar (cuenta contable faltante, período cerrado,
        _check_company, etc.), así que aislarla por línea es lo que
        garantiza que un solo producto problemático no revierta el conteo
        entero. Las líneas que fallan quedan marcadas con su error y no
        frenan a las demás; la sesión pasa a 'applied' de todos modos.
        """
        self.ensure_one()
        self._check_draft()

        # No eliminar este chequeo aunque parezca redundante con el ACL:
        # _is_inventory_mode() en el core (stock/models/stock_quant.py,
        # ~línea 1240) solo exige stock.group_stock_user para aplicar
        # inventory_quantity. El ACL de este módulo da write/unlink a ese
        # mismo grupo, y el groups= del botón en la vista es solo UI. Este
        # has_group() es la única barrera real contra que un usuario de
        # inventario común mueva stock llamando action_apply por RPC.
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise UserError(
                _(
                    "Solo un administrador de inventario puede aplicar un "
                    "conteo. Pedile a un responsable que la aplique."
                )
            )

        if not self.line_ids:
            raise UserError(
                _("La sesión '%s' no tiene líneas para aplicar.", self.name)
            )

        applied = 0
        failed = 0
        for line in self.line_ids:
            error_msg = False
            try:
                with self.env.cr.savepoint():
                    line_quants = line._apply_line()
                    if line.error:
                        failed += 1
                    elif line_quants:
                        line_quants.with_context(
                            inventory_mode=True,
                            set_inventory_quantity_auto_apply=True,
                        ).action_apply_inventory()
                        applied += 1
                    else:
                        applied += 1
            except Exception as e:
                # El savepoint revierte la escritura de line.error (y
                # cualquier cambio de la aplicación contable), así que se
                # persiste después, fuera de su alcance.
                error_msg = str(e)
                failed += 1
                _logger.exception(
                    "Conteo %s: falló la línea del producto %s",
                    self.name,
                    line.product_id.display_name,
                )
            if error_msg:
                line.error = error_msg

        self.write({"state": "applied", "date_applied": fields.Datetime.now()})
        _logger.info(
            "Conteo %s aplicado: %s líneas ajustadas, %s con error",
            self.name,
            applied,
            failed,
        )
        return True

    def action_scan_barcode(self, barcode):
        """Procesa un código escaneado y devuelve la acción para cargar cantidad.

        Si el producto ya está en la sesión, se reutiliza su línea en vez de
        crear una nueva: el usuario ve el total cargado y decide.
        """
        self.ensure_one()
        self._check_draft()

        barcode = (barcode or "").strip()
        if not barcode:
            return {"error": _("No se leyó ningún código.")}

        product = (
            self.env["product.product"]
            .with_company(self.company_id)
            .search([("barcode", "=", barcode)], limit=1)
        )
        if not product:
            return {
                "error": _("No hay ningún producto con el código %s.", barcode)
            }

        if not product.is_storable:
            return {
                "error": _(
                    "'%s' es un consumible o servicio: no maneja stock y no "
                    "se puede contar.",
                    product.display_name,
                )
            }

        line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if not line:
            line = self.env["stock.count.line"].create(
                {
                    "session_id": self.id,
                    "product_id": product.id,
                    "counted_qty": 0.0,
                }
            )

        return {
            "action": {
                "type": "ir.actions.act_window",
                "res_model": "stock.count.line",
                "res_id": line.id,
                "views": [
                    (
                        self.env.ref(
                            "stock_count_barcode.view_stock_count_line_quick_form"
                        ).id,
                        "form",
                    )
                ],
                "target": "new",
                "name": product.display_name,
            }
        }
