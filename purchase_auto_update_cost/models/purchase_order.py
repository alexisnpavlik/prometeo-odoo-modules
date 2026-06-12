from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        res = super(PurchaseOrder, self).button_confirm()
        for order in self:
            for line in order.order_line:
                if line.product_id and line.price_unit != 0.0:
                    price_unit = line.price_unit

                    # 1. Convert price to product's primary UoM if they are different
                    if (
                        line.product_uom
                        and line.product_id.uom_id
                        and line.product_uom != line.product_id.uom_id
                    ):
                        price_unit = line.product_uom._compute_price(
                            price_unit, line.product_id.uom_id
                        )

                    # 2. Convert price from purchase currency to company currency if they differ
                    if order.currency_id != order.company_id.currency_id:
                        price_unit = order.currency_id._convert(
                            price_unit,
                            order.company_id.currency_id,
                            order.company_id,
                            order.date_approve
                            or order.date_order
                            or fields.Date.today(),
                        )

                    # 3. Update the standard price (cost price) of the product
                    line.product_id.write({"standard_price": price_unit})
        return res
