# -*- coding: utf-8 -*-
import logging
import math
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

from .res_partner import FALLBACK_LEAD_TIME_DAYS

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
    category_ids = fields.Many2many(
        "product.category", string="Categorías a comprar",
        help="Elegí una o varias categorías. Vacío incluye todas las categorías.",
    )
    include_subcategories = fields.Boolean(
        string="Incluir subcategorías", default=True,
        help="Incluye también las categorías descendientes de las seleccionadas.",
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
    line_count = fields.Integer(
        string="Cantidad de líneas", compute="_compute_totals", store=True)
    low_confidence_count = fields.Integer(
        string="Líneas de baja confianza", compute="_compute_totals", store=True,
    )
    # Métricas de calidad del modelo. Comparar lo sugerido contra lo que el
    # usuario finalmente pidió dice más sobre si el módulo sirve que cualquier
    # métrica estadística de error.
    edit_rate = fields.Float(
        string="Tasa de edición", compute="_compute_quality_metrics", store=True,
        digits=(3, 2),
        help="Proporción de líneas cuya cantidad el usuario cambió. Por encima "
             "del 50% el modelo está mal calibrado para este negocio.",
    )
    mean_deviation = fields.Float(
        string="Desvío medio", compute="_compute_quality_metrics", store=True,
        digits=(16, 2),
        help="Promedio de lo que el usuario sumó o restó a la cantidad "
             "sugerida. Sistemáticamente positivo significa que el modelo "
             "sugiere de menos.",
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

    @api.depends("line_ids.was_edited", "line_ids.qty_final", "line_ids.qty_suggested")
    def _compute_quality_metrics(self):
        for suggestion in self:
            lines = suggestion.line_ids.filtered(lambda line: not line.is_manual)
            if not lines:
                suggestion.edit_rate = 0.0
                suggestion.mean_deviation = 0.0
                continue
            edited = lines.filtered("was_edited")
            suggestion.edit_rate = len(edited) / len(lines)
            suggestion.mean_deviation = sum(
                line.qty_final - line.qty_suggested for line in lines
            ) / len(lines)

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

    def _build_demand_series(self, model, products, warehouse=None):
        """Serie de demanda de esos productos según la ventana del modelo."""
        self.ensure_one()
        builder = self.env["prometeo.demand.series.builder"]
        date_from, date_to = self._demand_window(model)
        return builder.build(warehouse or self.warehouse_id, products.ids, date_from, date_to)

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

    def _estimate_demand(self, products, warehouse=None):
        """Estima la demanda de cada producto.

        Devuelve ({product_id: Estimate}, {product_id: modelo usado}). El modelo
        vuelve para poder dejarlo asentado en la línea: sin eso no hay forma de
        saber después con qué parámetros salió cada número.
        """
        self.ensure_one()
        estimates = {}
        models = {}
        for model, model_products in self._products_by_demand_model(products).items():
            series = self._build_demand_series(model, model_products, warehouse=warehouse)
            estimates.update(model.estimate(series))
            for product in model_products:
                models[product.id] = model
                if product.id in estimates:
                    estimates[product.id].observed_sales = {
                        "qty": series.total_qty(product.id),
                        "date_from": series.date_from.isoformat(),
                        "date_to": (series.date_to - timedelta(days=1)).isoformat(),
                    }
        return estimates, models

    # ------------------------------------------------------------------
    # Selección de productos
    # ------------------------------------------------------------------
    def _candidate_domain(self):
        """Dominio de los productos que pueden entrar en la sugerencia."""
        self.ensure_one()
        return self._category_product_domain() + [
            ("is_storable", "=", True),
            ("purchase_ok", "=", True),
            ("exclude_from_suggestion", "=", False),
            ("company_id", "in", [False, self.company_id.id]),
        ]

    def _category_product_domain(self):
        """Alcance común para calcular y validar los productos que se compran."""
        self.ensure_one()
        if not self.category_ids:
            return []
        return [("categ_id", "child_of" if self.include_subcategories else "in",
                 self.category_ids.ids)]

    def _candidate_products(self):
        self.ensure_one()
        return self.env["product.product"].search(self._candidate_domain())

    def _pick_seller(self, product):
        """Proveedor con el que se va a comprar este producto.

        Se elige por secuencia y precio, no con `_select_seller`: ese método
        filtra por cantidad mínima, y acá todavía no se sabe cuánto se va a
        pedir.

        No se exige que el proveedor sea de la compañía de la sugerencia. Odoo
        tampoco lo hace en `_get_filtered_sellers`: deja el alcance en manos de
        la regla de registro, y lo que el usuario puede leer es lo que puede
        usar. Exigir la igualdad rompe el caso normal de una lista de precios
        de compra centralizada en una compañía y sucursales que compran contra
        ella. Si la sucursal tiene su propio precio negociado, ese gana.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        sellers = product.seller_ids.filtered(lambda seller: (
            (not seller.date_start or seller.date_start <= today)
            and (not seller.date_end or seller.date_end >= today)
            and (not seller.product_id or seller.product_id == product)
        ))
        if not sellers:
            return self.env["product.supplierinfo"]
        own = sellers.filtered(lambda seller: seller.company_id == self.company_id)
        return min(own or sellers,
                   key=lambda seller: (seller.sequence, seller.price))

    def _seller_price(self, product, seller):
        """Precio por unidad de stock, expresado en la moneda de la sugerencia."""
        self.ensure_one()
        if not seller:
            return 0.0
        price = (seller.product_uom or product.uom_po_id)._compute_price(
            seller.price, product.uom_id)
        return seller.currency_id._convert(
            price, self.currency_id, self.company_id, fields.Date.context_today(self))

    # ------------------------------------------------------------------
    # Cantidad
    # ------------------------------------------------------------------
    def _target_quantity(self, estimate, lead_time_days, safety_stock,
                         on_hand, incoming, outgoing):
        """Cuánto falta para cubrir el plazo de entrega más los días objetivo.

        Lo comprometido en salidas pendientes suma: esa mercadería ya está
        vendida aunque siga en el depósito.

        El stock negativo se toma como cero. Restar un número negativo lo
        sumaría a la compra, y el módulo terminaría pidiendo cuatro años de
        stock de un producto que vende un tercio de unidad por día. En Odoo un
        saldo negativo casi nunca es demanda insatisfecha: son recepciones sin
        registrar. Se avisa en la línea en vez de comprar contra el error.
        """
        self.ensure_one()
        target = estimate.adu * (lead_time_days + self.coverage_days) + safety_stock
        return target - max(on_hand, 0.0) - incoming + outgoing

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

    def _should_include(self, product, estimate, coverage, lead_time, on_hand):
        """Filtro de prioridad: qué productos vale la pena mostrar.

        Los C son la cola larga del surtido. Listarlos todos cada semana
        entierra los A y B, que son los que mueven la caja, así que solo
        aparecen cuando van a quebrar antes de que llegue la reposición.
        """
        self.ensure_one()
        if estimate.adu <= 0 and on_hand > 0:
            # Stock muerto: no se vendió nada en la ventana y todavía queda.
            return False
        if product.abc_class == "c" and not self.company_id.suggestion_always_include_c:
            return coverage < lead_time
        return True

    def _coverage_days(self, on_hand, adu):
        """Cuántos días aguanta el stock actual al ritmo estimado.

        Con saldo negativo la cobertura es cero, no negativa: no hay stock que
        dure menos que nada, y una cobertura de -1400 días ordena la lista por
        magnitud del error de inventario en vez de por urgencia real.
        """
        if adu <= 0:
            return NO_DEMAND_COVERAGE_DAYS
        return max(on_hand, 0.0) / adu

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

    def _build_line_values(self, products, estimates, models, warehouse=None,
                           include_all=False, incoming_adjustments=None):
        """Métricas por almacén; la compra centralizada aplica los mínimos al final."""
        self.ensure_one()
        warehouse = warehouse or self.warehouse_id
        scoped = products.with_context(warehouse_id=warehouse.id)

        sellers = {product.id: self._pick_seller(product) for product in scoped}
        sellers_by_partner = {}
        for seller in sellers.values():
            if seller:
                sellers_by_partner.setdefault(seller.partner_id.id, seller)
        partners = self.env["res.partner"].browse(list(sellers_by_partner))
        measured = partners.with_context(
            allowed_company_ids=[self.company_id.id],
            advisor_receipt_warehouse_id=self.warehouse_id.id,
        )._measure_lead_times()

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
            lead_time, lead_source = self.env["res.partner"]._lead_time_from_measurement(
                seller, measured.get(seller.partner_id.id, (0, 0)) if seller else (0, 0))
            if warehouse != self.warehouse_id:
                lead_time += self.transfer_days
            safety_stock = model._safety_stock(
                estimate.sigma, lead_time, estimate.adu) if model else 0.0
            on_hand = product.qty_available
            incoming = product.incoming_qty + (incoming_adjustments or {}).get(product.id, 0)
            outgoing = product.outgoing_qty

            coverage = self._coverage_days(on_hand, estimate.adu)
            keep = product.id in existing
            if not include_all and not keep and not self._should_include(
                    product, estimate, coverage, lead_time, on_hand):
                continue

            raw = self._target_quantity(
                estimate, lead_time, safety_stock, on_hand, incoming, outgoing)
            qty = raw if include_all else self._apply_supplier_constraints(product, seller, raw)

            if not include_all and float_compare(qty, 0.0, precision_digits=rounding) <= 0 and not keep:
                continue

            values[product.id] = {
                "supplier_id": seller.partner_id.id if seller else False,
                "price_unit": self._seller_price(product, seller),
                "price_in_stock_uom": True,
                "qty_suggested": qty,
                "qty_final": qty,
                "adu": estimate.adu,
                "sigma": estimate.sigma,
                "confidence": estimate.confidence,
                "coverage_days_current": coverage,
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
                    observed_sales=estimate.observed_sales,
                ),
                "explanation": self._build_line_explanation(
                    estimate, on_hand, incoming, lead_time, safety_stock),
                "warnings": "\n".join(
                    estimate.warnings
                    + self._stock_warnings(product, on_hand)
                    + self._lead_time_warnings(seller, lead_time, lead_source)
                    + ([] if seller else [_(
                        "Sin proveedor: asigná uno y completá el precio antes de "
                        "generar la orden de compra.")])
                ) or False,
            }
        return values

    def _stock_warnings(self, product, on_hand):
        """Avisos sobre la calidad del dato de stock, no sobre la demanda."""
        self.ensure_one()
        if on_hand >= 0:
            return []
        return [_(
            "El stock figura en negativo (%(qty)s): probablemente falten "
            "recepciones por registrar. Se calculó como si fuera cero, así que "
            "la cantidad sugerida no contempla ese faltante.",
            qty=round(on_hand, 2),
        )]

    def _lead_time_warnings(self, seller, lead_time, source):
        """Avisa cuándo el plazo es una suposición y no una medición."""
        self.ensure_one()
        if source == "measured":
            return []
        if source == "configured":
            return [_(
                "El plazo de %(days)s días es el cargado en la ficha del "
                "proveedor: no hay suficientes compras recibidas para medirlo.",
                days=round(lead_time, 1),
            )]
        return [_(
            "No se pudo medir el plazo del proveedor ni hay uno cargado en su "
            "ficha, así que se supusieron %(days)s días. Si las órdenes de "
            "compra se registran cuando la mercadería ya llegó, la base no "
            "tiene forma de saber el plazo real: conviene cargarlo a mano.",
            days=round(lead_time, 1),
        )]

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
        computed = 0
        preserved = 0
        for suggestion in self:
            if suggestion.state not in ("draft", "computed"):
                raise UserError(_(
                    "Solo se pueden recalcular sugerencias en borrador o calculadas."
                ))
            metrics = suggestion.with_company(suggestion.company_id)._run_engine()
            preserved += suggestion._apply_metrics(metrics)
            computed += len(metrics)
            suggestion.write({
                "state": "computed",
                "date_computed": fields.Datetime.now(),
            })
            _logger.info(
                "Sugerencia %s recalculada: %s líneas, %s ediciones preservadas",
                suggestion.name, len(suggestion.line_ids), preserved,
            )
        return self._compute_notification(computed, preserved)

    def _compute_notification(self, computed, preserved):
        """Aviso de qué pasó, para que un recálculo no parezca no haber hecho nada."""
        if preserved:
            message = _(
                "%(computed)s líneas recalculadas, %(preserved)s ediciones "
                "manuales preservadas.",
                computed=computed, preserved=preserved,
            )
        else:
            message = _("%(computed)s líneas recalculadas.", computed=computed)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success" if computed else "warning",
                "message": message or _("No se encontró ningún producto a reponer."),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _apply_metrics(self, metrics):
        """Vuelca las métricas del motor en las líneas.

        Las líneas manuales o editadas conservan `qty_final`: el usuario ya
        decidió sobre ellas y un recálculo no puede pisar esa decisión.
        Devuelve cuántas ediciones se preservaron.
        """
        self.ensure_one()
        preserved = 0
        existing = {line.product_id.id: line for line in self.line_ids}
        to_create = []
        for product_id, line in existing.items():
            if product_id not in metrics:
                if line.is_manual or line.was_edited:
                    line.write({"qty_suggested": 0, "warnings": _(
                        "El producto ya no participa del cálculo. Se conserva la decisión manual; revisala.")})
                    preserved += 1
                else:
                    line.unlink()
        for product_id, vals in metrics.items():
            line = existing.get(product_id)
            if line:
                keep_qty = line.is_manual or line.was_edited
                line_vals = dict(vals)
                if keep_qty:
                    line_vals.pop("qty_final", None)
                    line_vals.pop("supplier_id", None)
                    line_vals.pop("price_unit", None)
                    line_vals.pop("price_in_stock_uom", None)
                    preserved += 1
                line.write(line_vals)
            else:
                to_create.append(dict(vals, suggestion_id=self.id, product_id=product_id))
        if to_create:
            self.env["prometeo.purchase.suggestion.line"].create(to_create)
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
        if self.category_ids:
            allowed = self.env["product.product"].search(
                self._category_product_domain() + [("id", "in", lines.product_id.ids)])
            outside = lines.product_id - allowed
            if outside:
                raise UserError(_(
                    "Hay productos fuera de las categorías seleccionadas. "
                    "Quitalos o dejá su cantidad en cero antes de comprar:\n%(products)s",
                    products="\n".join(outside.mapped("display_name")),
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
        order = self.env["purchase.order"].with_company(self.company_id).create({
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

    # ------------------------------------------------------------------
    # Automatización
    # ------------------------------------------------------------------
    @api.model
    def _cron_generate_suggestions(self):
        """Genera y calcula una sugerencia por almacén configurado.

        Sin esto el módulo depende de que alguien se acuerde de entrar. Con
        esto la sugerencia aparece sola y con una actividad asignada, que es la
        diferencia entre una herramienta que se usa y una que no.
        """
        warehouses = self.env["stock.warehouse"].search([
            ("auto_suggestion", "=", True),
        ])
        created = self.browse()
        for warehouse in warehouses:
            suggestion = self.with_company(warehouse.company_id).create({
                "warehouse_id": warehouse.id,
                "user_id": (warehouse.suggestion_user_id
                            or self.env.ref("base.user_admin")).id,
            })
            try:
                suggestion.action_compute()
            except Exception:
                _logger.exception(
                    "Falló el cálculo automático de la sugerencia de %s",
                    warehouse.display_name)
                continue
            suggestion._schedule_review_activity()
            created |= suggestion
        _logger.info("Sugerencias automáticas generadas: %s", len(created))
        return created

    def _schedule_review_activity(self):
        """Deja una actividad de revisión al responsable del almacén."""
        for suggestion in self:
            user = suggestion.warehouse_id.suggestion_user_id or suggestion.user_id
            if not user:
                continue
            suggestion.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary=_("Revisar la sugerencia de compra de %(warehouse)s",
                          warehouse=suggestion.warehouse_id.display_name),
                note=_("%(lines)s líneas sugeridas por un total de %(total)s.",
                       lines=suggestion.line_count,
                       total=suggestion.total_amount),
            )
        return True
