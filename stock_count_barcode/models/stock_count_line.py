import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

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

        Nota (C5): la búsqueda usa location_id exacto, sin bajar a
        sublocaciones. Si algún día se cuenta contra una ubicación padre que
        tiene hijas internas con stock, el teórico daría 0 y aplicar crearía
        un quant en el padre encima del que ya existe abajo. Hoy es
        inalcanzable (ninguna ubicación interna de esta base tiene hijas
        internas), pero queda documentado para el día que se creen
        sublocaciones de estante.
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

    @api.depends("product_id", "counted_qty", "session_id.location_id", "company_id")
    def _compute_theoretical_qty(self):
        """Lee el stock del sistema en tiempo real, nunca un valor congelado.

        Congelarlo al escanear haría que una venta ocurrida durante el conteo
        quede pisada por el ajuste. Para evitar un N+1 de búsquedas (una por
        línea) se agrupan todas las líneas del recordset por (empresa,
        producto, ubicación) y se hace un único _read_group sobre
        stock.quant por cada combinación de empresa/ubicación presente,
        repartiendo los totales a cada línea.
        """
        results_by_key = {}
        # Agrupamos por (company_id, location_id) para respetar el contexto
        # de empresa de cada sesión al leer los quants.
        lines_by_company_location = {}
        for line in self:
            if not (line.product_id and line.location_id):
                continue
            key = (line.company_id, line.location_id)
            lines_by_company_location.setdefault(key, self.env["stock.count.line"])
            lines_by_company_location[key] |= line

        for (company, location), lines in lines_by_company_location.items():
            product_ids = lines.product_id.ids
            grouped = (
                self.env["stock.quant"]
                .with_company(company)
                ._read_group(
                    [
                        ("product_id", "in", product_ids),
                        ("location_id", "=", location.id),
                    ],
                    groupby=["product_id"],
                    aggregates=["quantity:sum"],
                )
            )
            for product, qty_sum in grouped:
                results_by_key[(company.id, location.id, product.id)] = qty_sum

        for line in self:
            key = (line.company_id.id, line.location_id.id, line.product_id.id)
            line.theoretical_qty = results_by_key.get(key, 0.0)
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

    def unlink(self):
        """Impide borrar una línea cuya sesión no está en borrador.

        Igual que en la sesión: borrar líneas de un conteo aplicado
        falsificaría el registro de qué se contó.
        """
        for line in self:
            if line.session_id.state != "draft":
                raise UserError(
                    _(
                        "No se puede eliminar la línea del producto '%s': la "
                        "sesión '%s' no está en borrador.",
                        line.product_id.display_name,
                        line.session_id.name,
                    )
                )
        return super().unlink()

    def write(self, vals):
        """Bloquea la edición de líneas de una sesión ya aplicada.

        _apply_line() escribe 'error' durante action_apply(), pero esa
        escritura ocurre mientras la sesión todavía está en 'draft' (el
        estado pasa a 'applied' recién al final, en el write de la sesión),
        así que no choca con este bloqueo.
        """
        for line in self:
            if line.session_id.state == "applied":
                raise UserError(
                    _(
                        "No se puede modificar la línea del producto '%s': "
                        "la sesión '%s' ya fue aplicada.",
                        line.product_id.display_name,
                        line.session_id.name,
                    )
                )
        return super().write(vals)

    def _apply_line(self):
        """Prepara el quant de esta línea con la cantidad contada.

        No aplica el ajuste: solo escribe inventory_quantity. El que aplica es
        action_apply_inventory() sobre el conjunto de quants, en la sesión.

        Devuelve el quant preparado, o un recordset vacío si no hay nada que
        ajustar. Si la línea no se puede aplicar, setea self.error y devuelve
        un recordset vacío.
        """
        self.ensure_one()
        self.error = False

        if self.product_id.tracking != "none":
            self.error = _(
                "El producto '%s' se maneja por lotes o números de serie. "
                "Ajustalo a mano desde Inventario.",
                self.product_id.display_name,
            )
            _logger.warning(
                "Conteo: línea rechazada para el producto %s (id %s): se "
                "maneja por lotes o números de serie (tracking=%s).",
                self.product_id.display_name,
                self.product_id.id,
                self.product_id.tracking,
            )
            return self.env["stock.quant"]

        quants = self._get_quants()

        if len(quants) > 1:
            self.error = _(
                "El producto tiene %s quants en la ubicación (lotes, series o "
                "paquetes). Ajustalo a mano desde Inventario.",
                len(quants),
            )
            _logger.warning(
                "Conteo: línea rechazada para el producto %s (id %s): %s "
                "quants encontrados en la ubicación %s (lotes, series o "
                "paquetes).",
                self.product_id.display_name,
                self.product_id.id,
                len(quants),
                self.location_id.display_name,
            )
            return self.env["stock.quant"]

        if quants:
            quant = quants.with_company(self.company_id).with_context(
                inventory_mode=True
            )
            quant.inventory_quantity = self.counted_qty
            return quant

        if self.counted_qty <= 0:
            return self.env["stock.quant"]

        quant_model = (
            self.env["stock.quant"]
            .with_company(self.company_id)
            .with_context(inventory_mode=True)
        )
        return quant_model.create(
            {
                "product_id": self.product_id.id,
                "location_id": self.location_id.id,
                "inventory_quantity": self.counted_qty,
            }
        )
