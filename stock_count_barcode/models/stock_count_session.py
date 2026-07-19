import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
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

    def write(self, vals):
        """Bloquea empresa y ubicación una vez que la sesión tiene líneas."""
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
        return super().write(vals)

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
                        "Un conteo aplicado se corrige con una sesión nueva.",
                    )
                )
        self.write({"state": "draft"})
        return True

    def action_apply(self):
        """Aplica el conteo como ajuste de inventario nativo.

        Las líneas que fallan quedan marcadas con su error y no frenan a las
        demás: abortar toda la sesión por un producto con lotes obligaría a
        recontar la ubicación entera.
        """
        self.ensure_one()
        self._check_draft()

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

        quants = self.env["stock.quant"]
        failed = 0
        for line in self.line_ids:
            try:
                quants |= line._apply_line()
                if line.error:
                    failed += 1
            except Exception as e:
                line.error = str(e)
                failed += 1
                _logger.exception(
                    "Conteo %s: falló la línea del producto %s",
                    self.name,
                    line.product_id.display_name,
                )

        if quants:
            quants.with_context(inventory_mode=True).action_apply_inventory()

        self.write({"state": "applied", "date_applied": fields.Datetime.now()})
        _logger.info(
            "Conteo %s aplicado: %s líneas ajustadas, %s con error",
            self.name,
            len(quants),
            failed,
        )
        return True
