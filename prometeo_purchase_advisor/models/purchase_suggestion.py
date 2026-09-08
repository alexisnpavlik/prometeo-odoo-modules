# -*- coding: utf-8 -*-
import logging
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = 0.5


class PrometeoPurchaseSuggestion(models.Model):
    _name = "prometeo.purchase.suggestion"
    _description = "Sugerencia de compra"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_computed desc, id desc"

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True,
        default=lambda self: _("Nueva"),
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("computed", "Calculada"),
            ("confirmed", "Confirmada"),
            ("done", "Órdenes generadas"),
            ("cancel", "Cancelada"),
        ],
        string="Estado", default="draft", required=True, tracking=True, copy=False,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Almacén", required=True, tracking=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "in", self.env.companies.ids)], limit=1),
    )
    company_id = fields.Many2one(
        "res.company", string="Compañía", related="warehouse_id.company_id",
        store=True, readonly=True, index=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True,
    )
    user_id = fields.Many2one(
        "res.users", string="Responsable", default=lambda self: self.env.user,
        tracking=True,
    )
    date_computed = fields.Datetime(string="Calculada el", readonly=True, copy=False)
    coverage_days = fields.Integer(
        string="Días de cobertura", required=True,
        default=lambda self: self.env.company.suggestion_coverage_days or 30,
        help="Cuántos días de venta se quiere cubrir además del lead time del proveedor.",
    )
    demand_model_id = fields.Many2one(
        "prometeo.demand.model", string="Modelo de demanda",
        help="Fuerza un modelo para toda la corrida. Vacío usa la cascada "
             "producto → categoría → reglas → default de la compañía.",
    )
    line_ids = fields.One2many(
        "prometeo.purchase.suggestion.line", "suggestion_id", string="Líneas",
        copy=True,
    )
    purchase_order_ids = fields.One2many(
        "purchase.order", "suggestion_id", string="Órdenes de compra", readonly=True,
    )
    purchase_order_count = fields.Integer(
        string="Órdenes generadas", compute="_compute_purchase_order_count",
    )
    total_amount = fields.Monetary(
        string="Total estimado", compute="_compute_totals", store=True,
        currency_field="currency_id",
    )
    line_count = fields.Integer(string="Líneas", compute="_compute_totals", store=True)
    low_confidence_count = fields.Integer(
        string="Líneas de baja confianza", compute="_compute_totals", store=True,
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("line_ids.subtotal", "line_ids.confidence")
    def _compute_totals(self):
        for suggestion in self:
            lines = suggestion.line_ids
            suggestion.total_amount = sum(lines.mapped("subtotal"))
            suggestion.line_count = len(lines)
            suggestion.low_confidence_count = len(lines.filtered(
                lambda line: line.confidence < LOW_CONFIDENCE_THRESHOLD
            ))

    @api.depends("purchase_order_ids")
    def _compute_purchase_order_count(self):
        for suggestion in self:
            suggestion.purchase_order_count = len(suggestion.purchase_order_ids)

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nueva")) == _("Nueva"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "prometeo.purchase.suggestion") or _("Nueva")
        return super().create(vals_list)

    def unlink(self):
        """Una sugerencia que ya generó órdenes es evidencia de auditoría."""
        blocked = self.filtered(lambda s: s.state == "done")
        if blocked:
            raise UserError(_(
                "No se pueden borrar sugerencias que ya generaron órdenes de "
                "compra: %(names)s. Cancelalas si no las querés ver.",
                names=", ".join(blocked.mapped("name")),
            ))
        return super().unlink()

    # ------------------------------------------------------------------
    # Motor
    # ------------------------------------------------------------------
    def _run_engine(self):
        """Calcula las métricas de demanda de la sugerencia.

        Devuelve {product_id: dict de valores para la línea}. En esta fase el
        motor todavía no existe: devuelve vacío en vez de inventar números, que
        es lo único peor que no sugerir nada.
        """
        self.ensure_one()
        return {}

    def action_compute(self):
        """Recalcula las líneas preservando las ediciones manuales."""
        for suggestion in self:
            if suggestion.state not in ("draft", "computed"):
                raise UserError(_(
                    "Solo se pueden recalcular sugerencias en borrador o calculadas."
                ))
            metrics = suggestion._run_engine()
            preserved = suggestion._apply_metrics(metrics)
            suggestion.write({
                "state": "computed",
                "date_computed": fields.Datetime.now(),
            })
            _logger.info(
                "Sugerencia %s recalculada: %s líneas, %s ediciones preservadas",
                suggestion.name, len(suggestion.line_ids), preserved,
            )
        return True

    def _apply_metrics(self, metrics):
        """Vuelca las métricas del motor en las líneas.

        Las líneas manuales o editadas conservan `qty_final`: el usuario ya
        decidió sobre ellas y un recálculo no puede pisar esa decisión.
        Devuelve cuántas ediciones se preservaron.
        """
        self.ensure_one()
        preserved = 0
        existing = {line.product_id.id: line for line in self.line_ids}
        for product_id, vals in metrics.items():
            line = existing.get(product_id)
            if line:
                keep_qty = line.is_manual or line.was_edited
                line_vals = dict(vals)
                if keep_qty:
                    line_vals.pop("qty_final", None)
                    preserved += 1
                line.write(line_vals)
            else:
                self.env["prometeo.purchase.suggestion.line"].create(
                    dict(vals, suggestion_id=self.id, product_id=product_id)
                )
        return preserved

    # ------------------------------------------------------------------
    # Transiciones de estado
    # ------------------------------------------------------------------
    def action_confirm(self):
        for suggestion in self:
            if suggestion.state != "computed":
                raise UserError(_("Solo se pueden confirmar sugerencias calculadas."))
            if not suggestion.line_ids.filtered(lambda line: line.qty_final > 0):
                raise UserError(_(
                    "La sugerencia %(name)s no tiene ninguna línea con cantidad "
                    "mayor a cero.", name=suggestion.name,
                ))
        self.write({"state": "confirmed"})
        return True

    def action_cancel(self):
        self.write({"state": "cancel"})
        return True

    def action_draft(self):
        for suggestion in self:
            if suggestion.purchase_order_ids:
                raise UserError(_(
                    "La sugerencia %(name)s ya generó órdenes de compra. "
                    "Cancelá esas órdenes antes de volver a borrador.",
                    name=suggestion.name,
                ))
        self.write({"state": "draft"})
        return True

    # ------------------------------------------------------------------
    # Generación de órdenes de compra
    # ------------------------------------------------------------------
    def _lines_to_order(self):
        """Líneas que efectivamente se compran, validadas."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.qty_final > 0)
        if not lines:
            raise UserError(_(
                "No hay ninguna línea con cantidad mayor a cero en %(name)s.",
                name=self.name,
            ))
        without_supplier = lines.filtered(lambda line: not line.supplier_id)
        if without_supplier:
            raise UserError(_(
                "Estas líneas no tienen proveedor asignado:\n%(products)s",
                products="\n".join(
                    "- %s" % product.display_name
                    for product in without_supplier.mapped("product_id")
                ),
            ))
        return lines

    def action_create_purchase_orders(self):
        """Agrupa las líneas por proveedor y crea una orden en borrador por cada uno."""
        self.ensure_one()
        if self.state != "confirmed":
            raise UserError(_(
                "Confirmá la sugerencia antes de generar las órdenes de compra."
            ))
        lines = self._lines_to_order()

        zero_price = lines.filtered(lambda line: not line.price_unit)
        if zero_price:
            self.message_post(body=_(
                "Se generaron órdenes con %(count)s línea(s) a precio cero: %(products)s",
                count=len(zero_price),
                products=", ".join(zero_price.mapped("product_id.display_name")),
            ))

        by_supplier = defaultdict(lambda: self.env["prometeo.purchase.suggestion.line"])
        for line in lines:
            by_supplier[line.supplier_id] |= line

        orders = self.env["purchase.order"]
        for supplier, supplier_lines in by_supplier.items():
            orders |= self._create_purchase_order(supplier, supplier_lines)

        self.write({"state": "done"})
        self.message_post(body=_(
            "Se generaron %(count)s órdenes de compra en borrador.", count=len(orders),
        ))
        return self.action_view_purchase_orders()

    def _create_purchase_order(self, supplier, lines):
        """Crea una orden en borrador para un proveedor. Nunca la confirma."""
        self.ensure_one()
        order = self.env["purchase.order"].create({
            "partner_id": supplier.id,
            "company_id": self.company_id.id,
            "picking_type_id": self.warehouse_id.in_type_id.id,
            "origin": self.name,
            "suggestion_id": self.id,
        })
        order.order_line = [
            fields.Command.create(line._prepare_purchase_order_line_values(order))
            for line in lines
        ]
        return order

    def action_view_purchase_orders(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "purchase.purchase_rfq")
        action["domain"] = [("suggestion_id", "=", self.id)]
        action["context"] = {"default_suggestion_id": self.id}
        if len(self.purchase_order_ids) == 1:
            action["views"] = [(False, "form")]
            action["res_id"] = self.purchase_order_ids.id
        return action
