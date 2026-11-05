# -*- coding: utf-8 -*-
from odoo import Command
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


class CcaPosCommon(TestPoSCommon):
    """Fixtures compartidos por los tests del puente cuenta corriente - POS."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config  # ya creado por TestPoSCommon; recrearlo choca con el código del diario CSH
        cls.pay_later_pm.cca_is_checking_account = True
        cls.cca_partner = cls.env["res.partner"].create({
            "name": "Cliente CCA POS",
            "vat": "30111222",
        })
        cls.product_a = cls.env["product.product"].create({
            "name": "Producto A",
            "is_storable": True,
            "available_in_pos": True,
            "list_price": 100.0,
            "taxes_id": [Command.clear()],
        })
        cls.pos_user = cls.env["res.users"].create({
            "name": "Cajero CCA",
            "login": "cajero_cca",
            "company_id": cls.company.id,
            "company_ids": [Command.set(cls.company.ids)],
            "groups_id": [Command.set([cls.env.ref("point_of_sale.group_pos_user").id])],
        })

    def _cca_order_data(self, lines, payments, customer=None, **order_extra):
        """Arma el dict de un pedido del POS.

        lines: [(producto, cantidad, {"price_unit", "discount", "refunded_orderline_id"})].
        Si viene price_unit se recalculan price_subtotal y price_subtotal_incl.
        payments: [(metodo, monto)] o None (efectivo por el total).
        """
        specs = []
        for line in lines:
            product, qty = line[0], line[1]
            extra = dict(line[2]) if len(line) > 2 else {}
            price_unit = extra.pop("price_unit", None)
            specs.append((product, qty, price_unit, extra))
        data = self.create_ui_order_data(
            [{"product": p, "quantity": q, **extra} for p, q, _pu, extra in specs],
            customer=customer or False,
            payments=[],
        )
        total_incl = total_excl = 0.0
        for command, (_p, _q, price_unit, _extra) in zip(data["lines"], specs):
            vals = command[2]
            if price_unit is not None:
                vals["price_unit"] = price_unit
                after_discount = price_unit * (1 - vals.get("discount", 0.0) / 100.0)
                taxes = self.env["account.tax"].browse(vals["tax_ids"][0][2])
                if taxes:
                    res = taxes.compute_all(after_discount, self.currency, vals["qty"])
                    vals["price_subtotal"] = res["total_excluded"]
                    vals["price_subtotal_incl"] = res["total_included"]
                else:
                    vals["price_subtotal"] = vals["price_subtotal_incl"] = after_discount * vals["qty"]
            total_incl += vals["price_subtotal_incl"]
            total_excl += vals["price_subtotal"]
        if payments is None:
            cash = self.config.payment_method_ids.filtered(
                lambda pm: pm.is_cash_count and not pm.split_transactions
            )[:1]
            payments = [(cash, total_incl)]
        payment_cmds = [
            (0, 0, {
                "amount": amount,
                "name": data["date_order"],
                "payment_method_id": method.id,
            })
            for method, amount in payments
        ]
        data.update({
            "payment_ids": payment_cmds,
            "amount_paid": sum(amount for _m, amount in payments),
            "amount_total": total_incl,
            "amount_tax": total_incl - total_excl,
        })
        data.update(order_extra)
        return data
