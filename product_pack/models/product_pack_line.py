# Copyright 2019 Tecnativa - Ernesto Tejeda
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductPackLine(models.Model):
    _name = "product.pack.line"
    _description = "Product pack line"
    _rec_name = "product_id"

    parent_product_id = fields.Many2one(
        "product.product",
        "Parent Product",
        ondelete="cascade",
        index=True,
        required=True,
    )
    quantity = fields.Float(
        required=True,
        default=1.0,
        digits="Product UoS",
    )
    product_id = fields.Many2one(
        "product.product",
        "Product",
        ondelete="cascade",
        index=True,
        required=True,
    )

    # because on expand_pack_line we are searching for existing product, we
    # need to enforce this condition
    _sql_constraints = [
        (
            "product_uniq",
            "unique(parent_product_id, product_id)",
            "Product must be only once on a pack!",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        self._check_duplicated_pack_lines(vals_list)
        return super().create(vals_list)

    def _check_duplicated_pack_lines(self, vals_list):
        """Reject repeated components before the INSERT reaches the database.

        The product_uniq SQL constraint already forbids them, but letting the
        query fail logs a `bad query` error on every attempt. The lookup is
        done in sudo so a record rule hiding an existing line cannot make the
        check pass and blow up on the constraint anyway.
        """
        seen = set()
        for vals in vals_list:
            key = (vals.get("parent_product_id"), vals.get("product_id"))
            if not all(key):
                continue
            if key in seen:
                self._raise_duplicated_pack_line(key[1])
            seen.add(key)
        if not seen:
            return
        duplicated = self.sudo().search(
            [
                ("parent_product_id", "in", [key[0] for key in seen]),
                ("product_id", "in", [key[1] for key in seen]),
            ]
        )
        for line in duplicated:
            if (line.parent_product_id.id, line.product_id.id) in seen:
                self._raise_duplicated_pack_line(line.product_id.id)

    def _raise_duplicated_pack_line(self, product_id):
        product = self.env["product.product"].browse(product_id)
        raise ValidationError(
            _("Product must be only once on a pack!\nProduct: %s")
            % product.display_name
        )

    @api.constrains("product_id")
    def _check_recursion(self):
        """Check recursion on packs."""
        for line in self:
            parent_product = line.parent_product_id
            pack_lines = line
            while pack_lines:
                if parent_product in pack_lines.mapped("product_id"):
                    raise ValidationError(
                        _("You cannot set recursive packs.\nProduct id: %s")
                        % parent_product.id
                    )
                pack_lines = pack_lines.mapped("product_id.pack_line_ids")

    def _get_pack_line_price(self, pricelist, quantity, uom=None, date=False, **kwargs):
        self.ensure_one()
        if self.product_id._is_pack_to_be_handled():
            price = pricelist._get_product_price(
                self.product_id, quantity, uom=uom, date=date, **kwargs
            )
        else:
            price = pricelist._compute_price_rule(
                self.product_id, quantity, uom=uom, date=date, **kwargs
            )[self.product_id.id][0]
        return price * self.quantity

    def _pack_line_price_compute(
        self, price_type, uom=False, currency=False, company=False, date=False
    ):
        packs, no_packs = self.product_id.split_pack_products()

        pack_prices = {}
        # If the component is a pack
        for pack in packs:
            pack_prices[pack.id] = pack.lst_price
        # else
        no_pack_prices = no_packs._price_compute(
            price_type, uom, currency, company, date
        )

        prices = {**pack_prices, **no_pack_prices}
        for line in self:
            prices[line.product_id.id] *= line.quantity

        return prices
