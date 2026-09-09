# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models

from .product_product import ABC_SELECTION, XYZ_SELECTION
from .res_partner import FALLBACK_LEAD_TIME_DAYS

_logger = logging.getLogger(__name__)


class PrometeoPurchaseSuggestionLine(models.Model):
    _name = "prometeo.purchase.suggestion.line"
    _description = "Línea de sugerencia de compra"
    # Lo que está por quebrar y además vende mucho tiene que aparecer arriba.
    _order = "coverage_days_current asc, adu desc, id asc"

    suggestion_id = fields.Many2one(
        "prometeo.purchase.suggestion", string="Sugerencia", required=True,
        ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(
        "res.company", related="suggestion_id.company_id", store=True, readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="suggestion_id.currency_id", readonly=True,
    )
    state = fields.Selection(related="suggestion_id.state", store=True)

    product_id = fields.Many2one(
        "product.product", string="Producto", required=True,
        domain=[("purchase_ok", "=", True)], index=True,
    )
    supplier_id = fields.Many2one(
        "res.partner", string="Proveedor",
        help="Proveedor al que se le va a comprar. Determina el agrupamiento de "
             "las órdenes generadas.",
    )
    qty_suggested = fields.Float(
        string="Sugerido", readonly=True, digits="Product Unit of Measure",
        help="Cantidad que calculó el sistema, sin editar.",
    )
    qty_final = fields.Float(
        string="Cantidad", digits="Product Unit of Measure",
        help="Cantidad que efectivamente se va a pedir. Es la que va a la orden "
             "de compra. Poner cero descarta la línea sin borrar el registro.",
    )
    price_unit = fields.Float(
        string="Precio unitario", digits="Product Price",
    )
    price_in_stock_uom = fields.Boolean(
        default=True, readonly=True,
        help="Distingue los precios por unidad de stock de las sugerencias anteriores a la actualización.",
    )
    subtotal = fields.Monetary(
        string="Subtotal", compute="_compute_subtotal", store=True,
        currency_field="currency_id",
    )
    is_manual = fields.Boolean(
        string="Agregada a mano", readonly=True,
        help="La línea la agregó el usuario, no el cálculo.",
    )
    was_edited = fields.Boolean(
        string="Editada", compute="_compute_was_edited", store=True,
        help="La cantidad final difiere de la sugerida.",
    )

    # --- métricas de demanda -------------------------------------------
    adu = fields.Float(
        string="Venta diaria", readonly=True, digits=(16, 3),
        help="Demanda diaria promedio estimada.",
    )
    sigma = fields.Float(
        string="Desvío", readonly=True, digits=(16, 3),
        help="Desvío estándar de la demanda diaria.",
    )
    confidence = fields.Float(
        string="Confianza", readonly=True, digits=(3, 2),
        help="Indicador heurístico de calidad de datos, de 0 a 1; no es una "
             "probabilidad de acertar ni un intervalo estadístico. Por debajo "
             "de 0,5 conviene revisar la línea a mano.",
    )
    coverage_days_current = fields.Float(
        string="Cobertura (días)", readonly=True, digits=(16, 1),
        help="Cuántos días de venta cubre el stock actual al ritmo estimado.",
    )
    qty_on_hand = fields.Float(
        string="Stock", readonly=True, digits="Product Unit of Measure",
    )
    qty_incoming = fields.Float(
        string="En tránsito", readonly=True, digits="Product Unit of Measure",
        help="Cantidad en órdenes de compra confirmadas todavía no recibidas.",
    )
    lead_time_days = fields.Float(
        string="Lead time (días)", readonly=True, digits=(16, 1),
        help="Plazo de entrega medido sobre las compras reales al proveedor.",
    )
    safety_stock = fields.Float(
        string="Stock de seguridad", readonly=True, digits="Product Unit of Measure",
    )
    abc_class = fields.Selection(ABC_SELECTION, string="ABC", readonly=True)
    xyz_class = fields.Selection(XYZ_SELECTION, string="XYZ", readonly=True)

    # --- trazabilidad ---------------------------------------------------
    demand_model_id = fields.Many2one(
        "prometeo.demand.model", string="Modelo de demanda", readonly=True,
    )
    method_used = fields.Char(
        string="Método usado", readonly=True,
        help="Puede diferir del método pedido si hubo que degradar por falta de datos.",
    )
    params_snapshot = fields.Json(
        string="Parámetros usados", readonly=True,
        help="Configuración exacta con la que se calculó esta línea.",
    )
    explanation = fields.Text(
        string="Explicación", readonly=True,
        help="Por qué el sistema sugiere esta cantidad, en castellano.",
    )
    warnings = fields.Text(string="Advertencias", readonly=True)

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("qty_final", "price_unit", "price_in_stock_uom", "product_id.uom_po_id", "product_id.uom_id")
    def _compute_subtotal(self):
        for line in self:
            price = line.price_unit
            if not line.price_in_stock_uom:
                price = line.product_id.uom_po_id._compute_price(price, line.product_id.uom_id)
            line.subtotal = line.qty_final * price

    @api.depends("qty_final", "qty_suggested")
    def _compute_was_edited(self):
        for line in self:
            precision = line.product_id.uom_id.rounding or 0.01
            line.was_edited = abs(line.qty_final - line.qty_suggested) > precision / 2

    # ------------------------------------------------------------------
    # Onchange
    # ------------------------------------------------------------------
    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Completa proveedor y precio al elegir un producto a mano."""
        for line in self:
            if not line.product_id:
                continue
            line.is_manual = True
            seller = line._find_seller()
            if seller:
                line.supplier_id = seller.partner_id
                line.price_unit = line.suggestion_id._seller_price(line.product_id, seller)
                line.price_in_stock_uom = True
            line.qty_on_hand = line._current_qty_on_hand()

    def _find_seller(self):
        """Mejor proveedor del producto para el almacén de la sugerencia."""
        self.ensure_one()
        if not self.product_id:
            return self.env["product.supplierinfo"]
        return self.product_id._select_seller(
            partner_id=self.supplier_id or False,
            quantity=self.qty_final or 0.0,
            date=fields.Date.context_today(self),
            uom_id=self.product_id.uom_po_id,
        )

    def _current_qty_on_hand(self):
        """Stock del producto en el almacén de la sugerencia."""
        self.ensure_one()
        warehouse = self.suggestion_id.warehouse_id
        if not warehouse or not self.product_id:
            return 0.0
        return self.product_id.with_context(
            warehouse_id=warehouse.id).qty_available

    # ------------------------------------------------------------------
    # Generación de la orden de compra
    # ------------------------------------------------------------------
    def _prepare_purchase_order_line_values(self, order):
        """Valores de la línea de orden de compra correspondiente a esta línea."""
        self.ensure_one()
        product = self.product_id
        # qty_final está en la unidad de stock; la compra puede usar otra.
        qty = product.uom_id._compute_quantity(self.qty_final, product.uom_po_id)
        price = self.price_unit
        if self.price_in_stock_uom:
            price = product.uom_id._compute_price(price, product.uom_po_id)
        if order.currency_id and order.currency_id != self.currency_id:
            price = self.currency_id._convert(
                price, order.currency_id, order.company_id,
                fields.Date.context_today(self),
            )
        lead_time = self.lead_time_days or FALLBACK_LEAD_TIME_DAYS
        return {
            "product_id": product.id,
            "product_qty": qty,
            "product_uom": product.uom_po_id.id,
            "price_unit": price,
            "date_planned": fields.Datetime.now() + timedelta(days=lead_time),
        }
