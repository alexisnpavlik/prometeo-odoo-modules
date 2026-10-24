# -*- coding: utf-8 -*-

from odoo import Command, _, api, fields, models

from .simplify_options import is_option_active

# Solo el administrador puede cambiar la ruta del asistente Reabastecer.
EDIT_GROUP = "base.group_system"
BUY_ROUTE = "purchase_stock.route_warehouse0_buy"


class ProductReplenish(models.TransientModel):
    _inherit = "product.replenish"

    # Proveedor como contacto (se puede crear desde el asistente). El campo
    # nativo supplier_id es una línea de precio y no admite creación rápida.
    vendor_partner_id = fields.Many2one(
        "res.partner",
        string="Proveedor",
        compute="_compute_vendor_partner_id",
        store=True,
        readonly=False,
    )
    can_edit_route = fields.Boolean(
        string="Puede elegir la ruta",
        compute="_compute_can_edit_route",
    )

    simplify_vendor_partner = fields.Boolean(compute="_compute_can_edit_route")
    simplify_hide_route = fields.Boolean(compute="_compute_can_edit_route")

    # Sin dependencias Odoo no lo calcula en el registro nuevo del asistente.
    @api.depends("product_id")
    @api.depends_context("uid")
    def _compute_can_edit_route(self):
        """Ruta bloqueada (salvo admin) u oculta, y Proveedor como contacto, según Ajustes."""
        allowed = self._can_edit_route()
        vendor_partner = is_option_active(self.env, "replenish_vendor_partner")
        hide_route = is_option_active(self.env, "replenish_hide_route")
        for wizard in self:
            wizard.can_edit_route = allowed
            wizard.simplify_vendor_partner = vendor_partner
            wizard.simplify_hide_route = hide_route

    def _can_edit_route(self):
        """Con la opción de ruta bloqueada, solo el administrador la cambia."""
        return not is_option_active(self.env, "replenish_buy_locked") or self.env.user.has_group(EDIT_GROUP)

    @api.depends("supplier_id")
    def _compute_vendor_partner_id(self):
        """Toma el proveedor de la línea de precio elegida; sin línea, conserva el actual."""
        for wizard in self:
            if wizard.supplier_id:
                wizard.vendor_partner_id = wizard.supplier_id.partner_id

    @api.onchange("vendor_partner_id")
    def _onchange_vendor_partner_id(self):
        """Usa la línea de precio de ese proveedor si el producto ya la tiene."""
        self.supplier_id = self._find_supplierinfo(self.vendor_partner_id)

    def _find_supplierinfo(self, partner):
        """Línea de precio del producto para el proveedor dado (vacía si no hay)."""
        if not partner:
            return self.env["product.supplierinfo"]
        return self.product_tmpl_id.seller_ids.filtered(
            lambda line: line.partner_id == partner
            and (not line.product_id or line.product_id == self.product_id)
        )[:1]

    def _ensure_vendor_supplierinfo(self):
        """Crea la línea de precio del proveedor elegido si el producto no la tiene."""
        self.ensure_one()
        if not self.vendor_partner_id or not is_option_active(self.env, "replenish_vendor_partner"):
            return
        line = self._find_supplierinfo(self.vendor_partner_id)
        if not line:
            line = self.env["product.supplierinfo"].create({
                "partner_id": self.vendor_partner_id.id,
                "product_tmpl_id": self.product_tmpl_id.id,
                "price": self.product_id.standard_price,
            })
        self.supplier_id = line

    def _get_buy_route(self):
        """Devuelve la ruta Comprar si existe y está activa."""
        route = self.env.ref(BUY_ROUTE, raise_if_not_found=False)
        return route if route and route.active else self.env["stock.route"]

    @api.model
    def default_get(self, fields):
        """Propone la ruta Comprar (si está bloqueada) y el proveedor actual del producto."""
        res = super().default_get(fields)
        buy_route = self._get_buy_route()
        if "route_id" in fields and buy_route and is_option_active(self.env, "replenish_buy_locked"):
            res["route_id"] = buy_route.id
        if "vendor_partner_id" in fields and not res.get("vendor_partner_id"):
            supplier = self.env["product.supplierinfo"].browse(res.get("supplier_id"))
            tmpl = self.env["product.template"].browse(res.get("product_tmpl_id"))
            partner = supplier.partner_id or tmpl.seller_ids[:1].partner_id
            if partner:
                res["vendor_partner_id"] = partner.id
        return res

    def launch_replenishment(self):
        """Fuerza la ruta Comprar para quien no puede editarla, aunque llegue otra."""
        if not self._can_edit_route():
            buy_route = self._get_buy_route()
            if buy_route:
                self.route_id = buy_route
        for wizard in self:
            wizard._ensure_vendor_supplierinfo()
        if (
            len(self) == 1
            and is_option_active(self.env, "replenish_immediate")
            and "buy" in self.route_id.rule_ids.mapped("action")
        ):
            return self._replenish_receive_now()
        return super().launch_replenishment()

    def _replenish_receive_now(self):
        """Compra y recibe en el acto: crea la orden de compra, la confirma y
        valida la recepción, así el stock sube al confirmar el asistente."""
        self.ensure_one()
        partner = self.vendor_partner_id or self.supplier_id.partner_id
        if not partner:
            return super().launch_replenishment()
        # sudo acotado al flujo del asistente: el usuario del kiosco no tiene
        # por qué tener permisos de Compras ni de validar recepciones.
        order = self.env["purchase.order"].sudo().with_company(self.warehouse_id.company_id).create({
            "partner_id": partner.id,
            "company_id": self.warehouse_id.company_id.id,
            "picking_type_id": self.warehouse_id.in_type_id.id,
            "origin": _("Reabastecer (%s)", self.env.user.name),
            "order_line": [Command.create({
                "product_id": self.product_id.id,
                "product_qty": self.quantity,
                "product_uom": self.product_uom_id.id,
            })],
        })
        order.button_confirm()
        received = order._simplify_receive_now()
        return order._simplify_receive_notification(
            received, {"type": "ir.actions.act_window_close", "infos": {"done": True}}
        )
