from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools import format_amount

from .res_config_settings import edit_sale_price_enabled


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    price_sale = fields.Monetary(
        string="Precio de venta",
        compute="_compute_price_sale",
        store=True,
        readonly=False,
        precompute=True,
        help="Precio de venta a fijar en el producto al confirmar la compra. "
        "Se aplica la misma conversión de UdM y moneda que el precio de costo.",
    )

    @api.depends("product_id", "product_uom")
    def _compute_price_sale(self):
        """Trae el precio de venta actual del producto (el de la última carga)."""
        for line in self:
            line.price_sale = line._convert_price_from_company(line.product_id.list_price) if line.product_id else 0.0

    def _compute_price_unit_and_date_planned_and_name(self):
        """Usa el último costo cargado aunque el producto tenga tarifa de proveedor.

        Sin proveedor Odoo ya toma el costo; con proveedor tomaría el precio de la
        tarifa, que este módulo no actualiza y suele quedar viejo.
        """
        super()._compute_price_unit_and_date_planned_and_name()
        for line in self:
            if not line.product_id or line.invoice_lines or not line.company_id:
                continue
            cost = line.product_id.with_company(line.company_id).standard_price
            seller = line.product_id._select_seller(
                partner_id=line.partner_id,
                quantity=line.product_qty,
                date=line.order_id.date_order and line.order_id.date_order.date() or fields.Date.context_today(line),
                uom_id=line.product_uom,
                params=line._get_select_sellers_params(),
            )
            if cost and seller:
                line.price_unit = line._convert_price_from_company(cost)

    def _convert_price_from_company(self, price):
        """Inversa de _convert_price_to_company: de la UdM del producto y la moneda
        de la compañía a la UdM y la moneda de la línea."""
        self.ensure_one()
        if self.product_uom and self.product_id.uom_id and self.product_uom != self.product_id.uom_id:
            price = self.product_id.uom_id._compute_price(price, self.product_uom)
        order = self.order_id
        if order.currency_id and order.currency_id != order.company_id.currency_id:
            price = order.company_id.currency_id._convert(
                price, order.currency_id, order.company_id,
                order.date_order or fields.Date.today(),
            )
        return price

    def _convert_price_to_company(self, price):
        """Convierte un precio de la línea a la UdM del producto y a la moneda de la compañía."""
        self.ensure_one()

        # 1. Convert price to product's primary UoM if they are different
        if (
            self.product_uom
            and self.product_id.uom_id
            and self.product_uom != self.product_id.uom_id
        ):
            price = self.product_uom._compute_price(price, self.product_id.uom_id)

        # 2. Convert price from purchase currency to company currency if they differ
        order = self.order_id
        if order.currency_id != order.company_id.currency_id:
            price = order.currency_id._convert(
                price,
                order.company_id.currency_id,
                order.company_id,
                order.date_approve or order.date_order or fields.Date.today(),
            )
        return price


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    edit_sale_price = fields.Boolean(compute="_compute_edit_sale_price")
    price_update_warning = fields.Html(compute="_compute_price_update_warning", sanitize=False)

    def _compute_edit_sale_price(self):
        """Opción de Ajustes: la vista oculta la columna Precio de venta si está apagada."""
        enabled = edit_sale_price_enabled(self.env)
        for order in self:
            order.edit_sale_price = enabled

    def _price_updates(self):
        """Cambios que hará la confirmación: [(línea, campo, actual, nuevo)].

        Un precio en 0 no se aplica; uno igual al actual no se lista.
        """
        self.ensure_one()
        updates = []
        fields_prices = ["standard_price"]
        if edit_sale_price_enabled(self.env):
            fields_prices.append("list_price")
        for line in self.order_line.filtered("product_id"):
            product = line.product_id.with_company(self.company_id)
            for field in fields_prices:
                price = line.price_unit if field == "standard_price" else line.price_sale
                if not price:
                    continue
                new = line._convert_price_to_company(price)
                if self.company_id.currency_id.compare_amounts(new, product[field]):
                    updates.append((line, field, product[field], new))
        return updates

    @api.depends("state", "order_line.product_id", "order_line.price_unit",
                 "order_line.price_sale", "order_line.product_uom")
    def _compute_price_update_warning(self):
        """Aviso en borrador con los precios de producto que cambian al confirmar."""
        labels = {"standard_price": "Costo", "list_price": "Precio de venta"}
        for order in self:
            updates = order.state in ("draft", "sent") and order._price_updates()
            if not updates:
                order.price_update_warning = False
                continue
            cur = order.company_id.currency_id
            # Una línea por producto con todos sus cambios (costo · precio de venta).
            by_line = {}
            for line, field, old, new in updates:
                by_line.setdefault(line, []).append("%s %s → %s" % (
                    labels[field], format_amount(order.env, old, cur), format_amount(order.env, new, cur),
                ))
            items = "".join(
                "<li><b>%s</b>: %s</li>" % (line.product_id.display_name, " · ".join(changes))
                for line, changes in by_line.items()
            )
            order.price_update_warning = (
                "<b>Al confirmar se actualizan estos precios de producto:</b><ul class='mb-0'>%s</ul>" % items
            )

    def button_confirm(self):
        """Al confirmar, pasa a cada producto el costo y el precio de venta de la línea.

        Los cambios se calculan antes del super; el costo se graba en la compañía
        de la orden (standard_price depende de la compañía).
        """
        updates = {order: order._price_updates() for order in self}
        res = super().button_confirm()
        for order, changes in updates.items():
            products = self.env["product.product"]
            for line, field, _old, new in changes:
                line.product_id.with_company(order.company_id).write({field: new})
                products |= line.product_id
            # Los montos los registra el seguimiento de Costo y Precio de venta;
            # este mensaje deja a mano la compra que los cambió.
            for template in products.product_tmpl_id:
                template.message_post(
                    body=Markup("Precios actualizados por la compra %s") % order._get_html_link(),
                )
        return res
