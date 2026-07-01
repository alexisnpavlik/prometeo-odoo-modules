from odoo import fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    price_sale = fields.Monetary(
        string="Precio de venta",
        help="Precio de venta a fijar en el producto al confirmar la compra. "
        "Se aplica la misma conversión de UdM y moneda que el precio de costo.",
    )

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

    def button_confirm(self):
        res = super().button_confirm()
        for order in self:
            for line in order.order_line:
                if not line.product_id:
                    continue

                # Precio de costo -> standard_price del producto
                if line.price_unit != 0.0:
                    line.product_id.write(
                        {"standard_price": line._convert_price_to_company(line.price_unit)}
                    )

                # Precio de venta -> list_price del producto
                if line.price_sale != 0.0:
                    line.product_id.write(
                        {"list_price": line._convert_price_to_company(line.price_sale)}
                    )
        return res
