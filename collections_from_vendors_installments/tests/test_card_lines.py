# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCardLines(CviCommon):
    """Una venta puede llevar varios muebles, cada uno con su plan."""

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 3650
        self.table = self.env["product.product"].create({
            "name": "Mesa ratona", "type": "consu", "is_storable": True,
        })
        self.table_plan_6 = self.env["cvi.product.plan"].create({
            "product_tmpl_id": self.table.product_tmpl_id.id,
            "name": "6 cuotas",
            "installment_count": 6,
            "installment_amount": 3000.0,
            "frequency": "monthly",
        })
        self.table_plan_weekly = self.env["cvi.product.plan"].create({
            "product_tmpl_id": self.table.product_tmpl_id.id,
            "name": "8 semanas",
            "installment_count": 8,
            "installment_amount": 2000.0,
            "frequency": "weekly",
        })

    def _card(self, lines):
        return self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
            "line_ids": [(0, 0, vals) for vals in lines],
        })

    def _two_lines(self):
        """Ropero a 12 x 10.000 y mesa a 6 x 3.000."""
        return self._card([
            {"product_id": self.product.id, "plan_id": self.plan_12.id, "quantity": 1},
            {"product_id": self.table.id, "plan_id": self.table_plan_6.id, "quantity": 1},
        ])

    # --- composición del precio ---

    def test_total_is_the_sum_of_the_line_subtotals(self):
        card = self._two_lines()
        self.assertEqual(card.amount_total, 12 * 10000.0 + 6 * 3000.0)

    def test_schedule_length_is_the_longest_plan(self):
        self.assertEqual(self._two_lines().installment_count, 12)

    def test_first_installment_adds_up_both_lines(self):
        """La cuota que el vendedor pronuncia es la suma de lo que aporta cada mueble."""
        self.assertEqual(self._two_lines().installment_amount, 13000.0)

    def test_quantity_multiplies_what_the_line_contributes(self):
        card = self._card([
            {"product_id": self.product.id, "plan_id": self.plan_12.id, "quantity": 2},
        ])
        self.assertEqual(card.line_ids[0].amount_per_installment, 20000.0)
        self.assertEqual(card.amount_total, 12 * 20000.0)

    # --- calendario con cuotas variables ---

    def test_installments_drop_when_the_short_plan_ends(self):
        """Cuando se termina el plan corto, la cuota baja. Es el punto del diseño."""
        card = self._two_lines()
        card._cvi_generate_installments()
        by_seq = {i.sequence: i.amount for i in card.installment_ids}
        self.assertEqual(by_seq[1], 13000.0)
        self.assertEqual(by_seq[6], 13000.0)
        self.assertEqual(by_seq[7], 10000.0)
        self.assertEqual(by_seq[12], 10000.0)

    def test_schedule_sums_exactly_the_total(self):
        """No hay resto que repartir: el total sale de los planes, no de una división."""
        card = self._two_lines()
        card._cvi_generate_installments()
        self.assertEqual(
            sum(card.installment_ids.mapped("amount")), card.amount_total
        )

    def test_schedule_has_one_installment_per_period(self):
        card = self._two_lines()
        card._cvi_generate_installments()
        self.assertEqual(len(card.installment_ids), 12)

    def test_commission_is_the_first_period_of_the_whole_sale(self):
        card = self._two_lines()
        card._cvi_generate_installments()
        commission = card.installment_ids.filtered("is_commission")
        self.assertEqual(len(commission), 1)
        self.assertEqual(commission.amount, 13000.0)

    # --- reglas ---

    def test_mixing_frequencies_is_rejected(self):
        """Dos ritmos de cobro darían dos calendarios: no hay tarjeta posible."""
        with self.assertRaises(ValidationError):
            self._card([
                {"product_id": self.product.id, "plan_id": self.plan_12.id},
                {"product_id": self.table.id, "plan_id": self.table_plan_weekly.id},
            ])

    def test_a_line_needs_a_plan_of_its_own_product(self):
        with self.assertRaises(ValidationError):
            self._card([
                {"product_id": self.product.id, "plan_id": self.table_plan_6.id},
            ])

    def test_lines_are_frozen_after_confirming(self):
        """RN-05: la mercadería no se toca una vez confirmada la venta."""
        card = self._two_lines()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.line_ids[0].quantity = 5

    def test_lines_cannot_be_added_after_confirming(self):
        card = self._two_lines()
        card.action_confirm()
        with self.assertRaises(UserError):
            self.env["cvi.card.line"].create({
                "card_id": card.id,
                "product_id": self.table.id,
                "plan_id": self.table_plan_6.id,
            })

    def test_lines_cannot_be_removed_after_confirming(self):
        card = self._two_lines()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.line_ids[0].unlink()

    def test_lines_can_be_edited_while_draft(self):
        card = self._two_lines()
        card.line_ids[0].quantity = 3
        self.assertEqual(card.line_ids[0].amount_per_installment, 30000.0)

    # --- stock ---

    def test_confirming_moves_every_line_out_of_the_vendor_stock(self):
        quant = self.env["stock.quant"]
        location = self.vendor_user._cvi_get_location()
        quant.with_context(inventory_mode=True).create({
            "product_id": self.table.id,
            "location_id": location.id,
            "inventory_quantity": 10,
        }).action_apply_inventory()
        before_wardrobe = quant._get_available_quantity(self.product, location)
        before_table = quant._get_available_quantity(self.table, location)
        card = self._two_lines()
        card.action_confirm()
        self.assertEqual(
            quant._get_available_quantity(self.product, location), before_wardrobe - 1
        )
        self.assertEqual(
            quant._get_available_quantity(self.table, location), before_table - 1
        )

    def test_the_picking_has_a_move_per_product(self):
        quant = self.env["stock.quant"]
        location = self.vendor_user._cvi_get_location()
        quant.with_context(inventory_mode=True).create({
            "product_id": self.table.id,
            "location_id": location.id,
            "inventory_quantity": 10,
        }).action_apply_inventory()
        card = self._two_lines()
        card.action_confirm()
        self.assertEqual(len(card.picking_id.move_ids), 2)

    def test_two_lines_of_the_same_product_are_checked_together(self):
        """Mirarlas por separado dejaría pasar una venta sin existencias suficientes."""
        location = self.vendor_user._cvi_get_location()
        available = self.env["stock.quant"]._get_available_quantity(
            self.product, location
        )
        card = self._card([
            {"product_id": self.product.id, "plan_id": self.plan_12.id,
             "quantity": available},
            {"product_id": self.product.id, "plan_id": self.plan_12.id,
             "quantity": 1},
        ])
        with self.assertRaises(UserError):
            card.action_confirm()

    # --- compatibilidad con la carga de un solo mueble ---

    def test_creating_with_the_old_single_product_shape_still_works(self):
        """Cargar product_id y plan_id sin líneas sigue funcionando: se traduce en una.

        Es lo que mantiene andando el circuito de una venta de un solo mueble, que es
        el caso más común en la calle.
        """
        card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": self.plan_12.id,
            "quantity": 1.0,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
        })
        self.assertEqual(len(card.line_ids), 1)
        self.assertEqual(card.line_ids[0].product_id, self.product)
        self.assertEqual(card.product_id, self.product)
        self.assertEqual(card.amount_total, 120000.0)

    def test_header_reflects_the_first_line(self):
        card = self._two_lines()
        self.assertEqual(card.product_id, self.product)
        self.assertEqual(card.plan_id, self.plan_12)
        self.assertEqual(card.line_count, 2)
