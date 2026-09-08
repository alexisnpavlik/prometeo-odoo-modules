# -*- coding: utf-8 -*-
import logging
import math
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

_logger = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = 0.5

# Cobertura que se le asigna a un producto sin demanda estimada. Es un centinela
# alto a propósito: el listado ordena por cobertura ascendente, y lo que no se
# vende tiene que quedar último, no primero.
NO_DEMAND_COVERAGE_DAYS = 9999.0


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
    def _demand_window(self, model):
        """Ventana de análisis: [date_from, date_to), con date_to exclusivo.

        Termina ayer a propósito. El día en curso está incompleto y meterlo
        arrastra el promedio para abajo, sobre todo si se calcula a la mañana.
        """
        self.ensure_one()
        builder = self.env["prometeo.demand.series.builder"]
        date_to = builder._today(builder._timezone())
        return date_to - timedelta(days=model.lookback_days), date_to

    def _build_demand_series(self, model, products):
        """Serie de demanda de esos productos según la ventana del modelo."""
        self.ensure_one()
        builder = self.env["prometeo.demand.series.builder"]
        date_from, date_to = self._demand_window(model)
        return builder.build(self.warehouse_id, products.ids, date_from, date_to)

    def _products_by_demand_model(self, products):
        """Agrupa los productos por el modelo de demanda que les toca.

        Cada modelo tiene su propia ventana de historia, así que se arma una
        serie por modelo en vez de una sola para todos.
        """
        self.ensure_one()
        if self.demand_model_id:
            return {self.demand_model_id: products}
        resolved = self.env["prometeo.demand.model.rule"]._resolve_model_for_products(
            products)
        grouped = defaultdict(lambda: self.env["product.product"])
        for product in products:
            model = resolved.get(product.id)
            if model:
                grouped[model] |= product
            else:
                _logger.warning(
                    "Producto %s sin modelo de demanda resoluble: se omite",
                    product.display_name,
                )
        return grouped

    def _estimate_demand(self, products):
        """Estima la demanda de cada producto.

        Devuelve ({product_id: Estimate}, {product_id: modelo usado}). El modelo
        vuelve para poder dejarlo asentado en la línea: sin eso no hay forma de
        saber después con qué parámetros salió cada número.
        """
        self.ensure_one()
        estimates = {}
        models = {}
        for model, model_products in self._products_by_demand_model(products).items():
            series = self._build_demand_series(model, model_products)
            estimates.update(model.estimate(series))
            for product in model_products:
                models[product.id] = model
        return estimates, models

    # ------------------------------------------------------------------
    # Selección de productos
    # ------------------------------------------------------------------
    def _candidate_domain(self):
        """Dominio de los productos que pueden entrar en la sugerencia."""
        self.ensure_one()
        return [
            ("is_storable", "=", True),
            ("purchase_ok", "=", True),
            ("exclude_from_suggestion", "=", False),
            ("seller_ids", "!=", False),
            ("company_id", "in", [False, self.company_id.id]),
        ]

    def _candidate_products(self):
        self.ensure_one()
        return self.env["product.product"].search(self._candidate_domain())

    def _pick_seller(self, product):
        """Proveedor con el que se va a comprar este producto.

        Se elige por secuencia y precio, no con `_select_seller`: ese método
        filtra por cantidad, y acá todavía no se sabe cuánto se va a pedir.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        sellers = product.seller_ids.filtered(lambda seller: (
            (not seller.company_id or seller.company_id == self.company_id)
            and (not seller.date_start or seller.date_start <= today)
            and (not seller.date_end or seller.date_end >= today)
        ))
        if not sellers:
            return self.env["product.supplierinfo"]
        return min(sellers, key=lambda seller: (seller.sequence, seller.price))

    # ------------------------------------------------------------------
    # Cantidad
    # ------------------------------------------------------------------
    def _target_quantity(self, estimate, lead_time_days, safety_stock,
                         on_hand, incoming, outgoing):
        """Cuánto falta para cubrir el plazo de entrega más los días objetivo.

        Lo comprometido en salidas pendientes suma: esa mercadería ya está
        vendida aunque siga en el depósito.
        """
        self.ensure_one()
        target = estimate.adu * (lead_time_days + self.coverage_days) + safety_stock
        return target - on_hand - incoming + outgoing

    def _apply_supplier_constraints(self, product, seller, qty):
        """Ajusta la cantidad a lo que el proveedor realmente acepta vender.

        El mínimo se aplica antes del bulto y no al revés como decía el spec:
        redondear al bulto primero y después subir al mínimo deja una cantidad
        que no es múltiplo de nada.

        Todo se calcula en la unidad de stock. La conversión a la unidad de
        compra se hace recién al armar la orden.
        """
        self.ensure_one()
        if qty <= 0:
            return 0.0
        if seller and seller.min_qty:
            min_qty = seller.min_qty
            if seller.product_uom and seller.product_uom != product.uom_id:
                min_qty = seller.product_uom._compute_quantity(
                    min_qty, product.uom_id)
            qty = max(qty, min_qty)
        packagings = product.packaging_ids.filtered(
            lambda pack: pack.purchase and pack.qty > 0)
        if packagings:
            pack = min(packagings, key=lambda pack: pack.qty)
            qty = math.ceil(qty / pack.qty) * pack.qty
        return float_round(
            qty, precision_rounding=product.uom_id.rounding or 0.01,
            rounding_method="UP")

    def _coverage_days(self, on_hand, adu):
        """Cuántos días aguanta el stock actual al ritmo estimado."""
        if adu <= 0:
            return NO_DEMAND_COVERAGE_DAYS
        return on_hand / adu

    # ------------------------------------------------------------------
    # Motor
    # ------------------------------------------------------------------
    def _run_engine(self):
        """Calcula las líneas de la sugerencia.

        Devuelve {product_id: dict de valores para la línea}.
        """
        self.ensure_one()
        products = self._candidate_products()
        if not products:
            return {}
        estimates, models = self._estimate_demand(products)
        return self._build_line_values(products, estimates, models)

    def _build_line_values(self, products, estimates, models):
        self.ensure_one()
        warehouse = self.warehouse_id
        scoped = products.with_context(warehouse_id=warehouse.id)

        sellers = {product.id: self._pick_seller(product) for product in scoped}
        sellers_by_partner = {}
        for seller in sellers.values():
            if seller:
                sellers_by_partner.setdefault(seller.partner_id.id, seller)
        partners = self.env["res.partner"].browse(list(sellers_by_partner))
        lead_times = partners._lead_time_for_suggestion(sellers_by_partner)

        existing = set(self.line_ids.mapped("product_id").ids)
        rounding = self.env["decimal.precision"].precision_get(
            "Product Unit of Measure")
        values = {}
        for product in scoped:
            estimate = estimates.get(product.id)
            if not estimate:
                continue
            seller = sellers[product.id]
            model = models.get(product.id)
            lead_time = lead_times.get(seller.partner_id.id, 0.0) if seller else 0.0
            safety_stock = model._safety_stock(
                estimate.sigma, lead_time, estimate.adu) if model else 0.0
            on_hand = product.qty_available
            incoming = product.incoming_qty
            outgoing = product.outgoing_qty

            raw = self._target_quantity(
                estimate, lead_time, safety_stock, on_hand, incoming, outgoing)
            qty = self._apply_supplier_constraints(product, seller, raw)

            keep = product.id in existing
            if float_compare(qty, 0.0, precision_digits=rounding) <= 0 and not keep:
                continue

            values[product.id] = {
                "supplier_id": seller.partner_id.id if seller else False,
                "price_unit": seller.price if seller else 0.0,
                "qty_suggested": qty,
                "qty_final": qty,
                "adu": estimate.adu,
                "sigma": estimate.sigma,
                "confidence": estimate.confidence,
                "coverage_days_current": self._coverage_days(on_hand, estimate.adu),
                "qty_on_hand": on_hand,
                "qty_incoming": incoming,
                "lead_time_days": lead_time,
                "safety_stock": safety_stock,
                "abc_class": product.abc_class,
                "xyz_class": product.xyz_class,
                "demand_model_id": model.id if model else False,
                "method_used": estimate.method_used,
                "params_snapshot": dict(
                    model._params_snapshot() if model else {},
                    coverage_days=self.coverage_days,
                    lead_time_days=lead_time,
                ),
                "explanation": self._build_line_explanation(
                    estimate, on_hand, incoming, lead_time, safety_stock),
                "warnings": "\n".join(estimate.warnings) or False,
            }
        return values

    def _build_line_explanation(self, estimate, on_hand, incoming, lead_time,
                                safety_stock):
        """Texto completo: la demanda que estimó el motor más el contexto de stock."""
        self.ensure_one()
        parts = [estimate.explanation] if estimate.explanation else []
        coverage = self._coverage_days(on_hand, estimate.adu)
        if coverage < NO_DEMAND_COVERAGE_DAYS:
            parts.append(_(
                "Quedan %(on_hand)s unidades, que cubren %(days)s días.",
                on_hand=round(on_hand, 2), days=round(coverage, 1),
            ))
        else:
            parts.append(_(
                "Quedan %(on_hand)s unidades y no hay demanda estimada.",
                on_hand=round(on_hand, 2),
            ))
        if incoming:
            parts.append(_(
                "Ya hay %(incoming)s unidades en camino.", incoming=round(incoming, 2),
            ))
        parts.append(_(
            "Plazo de entrega del proveedor: %(lead)s días. Se compra para "
            "cubrir %(coverage)s días más, con %(safety)s unidades de colchón.",
            lead=round(lead_time, 1), coverage=self.coverage_days,
            safety=round(safety_stock, 2),
        ))
        return " ".join(parts)

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
