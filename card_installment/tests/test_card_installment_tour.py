from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged("post_install", "-at_install")
class TestCardInstallmentTour(TestPointOfSaleHttpCommon):
    """Botón Cuotas del POS: respeta la lista de precios, descuentos y precios manuales."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env

        cls.product_a = env["product.product"].create({
            "name": "Mochila A",
            "list_price": 32000,
            "available_in_pos": True,
            "taxes_id": [(5, 0, 0)],
        })
        cls.product_b = env["product.product"].create({
            "name": "Mochila B",
            "list_price": 26300,
            "available_in_pos": True,
            "taxes_id": [(5, 0, 0)],
        })

        # Lista "mayorista": precio fijo distinto al público, como en prod.
        cls.pricelist = env["product.pricelist"].create({
            "name": "Lista Mayorista Test",
            "currency_id": cls.main_pos_config.currency_id.id,
            "item_ids": [
                (0, 0, {
                    "applied_on": "1_product",
                    "product_tmpl_id": cls.product_a.product_tmpl_id.id,
                    "compute_price": "fixed",
                    "fixed_price": 27000,
                }),
                (0, 0, {
                    "applied_on": "1_product",
                    "product_tmpl_id": cls.product_b.product_tmpl_id.id,
                    "compute_price": "fixed",
                    "fixed_price": 19700,
                }),
            ],
        })

        card = env["account.card"].create({"name": "Tarjeta Test"})
        env["account.card.installment"].create([
            {"card_id": card.id, "name": "Plan 1", "installment": 1, "surcharge_coefficient": 1.0},
            {"card_id": card.id, "name": "Plan 6", "installment": 6, "surcharge_coefficient": 1.10},
            {"card_id": card.id, "name": "Plan 12", "installment": 12, "surcharge_coefficient": 1.40},
        ])
        card_journal = env["account.journal"].create({
            "name": "Card Test",
            "type": "bank",
            "code": "CRDT",
            "company_id": cls.main_pos_config.company_id.id,
        })
        card_method = env["pos.payment.method"].create({
            "name": "Tarjeta Test",
            "journal_id": card_journal.id,
            "outstanding_account_id": cls.inbound_payment_method_line.payment_account_id.id,
            "card_id": card.id,
        })

        cls.main_pos_config.write({
            "use_pricelist": True,
            "pricelist_id": cls.pricelist.id,
            "available_pricelist_ids": [(6, 0, cls.pricelist.ids)],
            "payment_method_ids": [(4, card_method.id)],
            "module_pos_discount": True,
            "discount_product_id": env.ref("pos_discount.product_product_consumable").id,
            "discount_pc": 15,
        })
        # En prod todas las cajas tienen pos_pricelist_enforce activo (re-aplica la
        # lista al tocar Pagar): si está instalado, probar junto con él.
        if "pricelist_enforce" in cls.main_pos_config._fields:
            cls.main_pos_config.pricelist_enforce = True

    def test_pricelist_with_discount_last(self):
        self.start_pos_tour("card_installment_pricelist_discount_last")

    def test_discount_not_last(self):
        self.start_pos_tour("card_installment_discount_not_last")

    def test_surcharge_full_payment(self):
        self.start_pos_tour("card_installment_surcharge_full")

    def test_manual_price(self):
        self.start_pos_tour("card_installment_manual_price")

    def test_change_plan(self):
        self.start_pos_tour("card_installment_change_plan")

    def test_split_payment(self):
        self.start_pos_tour("card_installment_split_payment")

    def test_surcharge_to_surcharge(self):
        self.start_pos_tour("card_installment_surcharge_to_surcharge")

    def test_price_edited_between(self):
        self.start_pos_tour("card_installment_price_edited_between")

    def test_validate_order(self):
        """Venta validada: lo grabado en pos.order (lo que se factura) respeta la lista."""
        self.start_pos_tour("card_installment_validate_order")
        order = self.main_pos_config.current_session_id.order_ids
        self.assertEqual(len(order), 1)
        prices = {line.product_id: line.price_unit for line in order.lines}
        self.assertAlmostEqual(prices[self.product_a], 29700)
        self.assertAlmostEqual(prices[self.product_b], 21670)
        discount = self.main_pos_config.discount_product_id
        self.assertAlmostEqual(prices[discount], -15411)
        self.assertAlmostEqual(order.amount_total, 87329)
        self.assertAlmostEqual(sum(order.payment_ids.mapped("amount")), 87329)
        self.assertEqual(order.state, "paid")
