import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StockCountLine(models.Model):
    _name = "stock.count.line"
    _description = "Línea de conteo de stock"
    _order = "id desc"

    session_id = fields.Many2one(
        "stock.count.session",
        string="Sesión",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        ondelete="restrict",
    )
    barcode = fields.Char(
        string="Código de barras",
        related="product_id.barcode",
        readonly=True,
    )
    uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad",
        related="product_id.uom_id",
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        related="session_id.company_id",
        store=True,
        readonly=True,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Ubicación",
        related="session_id.location_id",
        readonly=True,
    )
    state = fields.Selection(related="session_id.state", readonly=True)
    counted_qty = fields.Float(
        string="Contado",
        digits="Product Unit of Measure",
        default=0.0,
    )
    theoretical_qty = fields.Float(
        string="Sistema",
        digits="Product Unit of Measure",
        compute="_compute_theoretical_qty",
    )
    difference_qty = fields.Float(
        string="Diferencia",
        digits="Product Unit of Measure",
        compute="_compute_theoretical_qty",
    )
    error = fields.Char(string="Error", readonly=True, copy=False)

    _sql_constraints = [
        (
            "product_uniq_per_session",
            "unique(session_id, product_id)",
            "El producto ya está cargado en esta sesión de conteo.",
        ),
    ]

    def _get_quants(self):
        """Devuelve los quants del producto en la ubicación de la sesión.

        Se lee en el contexto de empresa de la sesión para no mezclar stock
        entre sucursales.
        """
        self.ensure_one()
        return (
            self.env["stock.quant"]
            .with_company(self.company_id)
            .search(
                [
                    ("product_id", "=", self.product_id.id),
                    ("location_id", "=", self.location_id.id),
                ]
            )
        )

    @api.depends("product_id", "counted_qty", "session_id.location_id")
    def _compute_theoretical_qty(self):
        """Lee el stock del sistema en tiempo real, nunca un valor congelado.

        Congelarlo al escanear haría que una venta ocurrida durante el conteo
        quede pisada por el ajuste.
        """
        for line in self:
            quants = line._get_quants() if line.product_id and line.location_id else False
            line.theoretical_qty = sum(quants.mapped("quantity")) if quants else 0.0
            line.difference_qty = line.counted_qty - line.theoretical_qty

    @api.constrains("counted_qty")
    def _check_counted_qty(self):
        """Una cantidad contada negativa siempre es un error de carga."""
        for line in self:
            if line.counted_qty < 0:
                raise ValidationError(
                    _(
                        "La cantidad contada de '%s' no puede ser negativa.",
                        line.product_id.display_name,
                    )
                )
