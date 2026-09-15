# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged, new_test_user
from .common import PurchaseAdvisorCommon


@tagged('post_install', '-at_install')
class TestBudget(PurchaseAdvisorCommon):
    def _budget_suggestion(self, budget=1000):
        self.uom_unit.rounding = 1
        self.uom_dozen.rounding = 1
        self.product_a.supplier_taxes_id = False
        self.product_b.supplier_taxes_id = False
        return self._make_suggestion(budget_enabled=True, budget_amount=budget, state='computed', lines=[
            dict(product_id=self.product_a.id, supplier_id=self.supplier_a.id,
                 qty_suggested=10, qty_final=10, price_unit=100, adu=5,
                 coverage_days_current=1, lead_time_days=10),
            dict(product_id=self.product_b.id, supplier_id=self.supplier_a.id,
                 qty_suggested=10, qty_final=10, price_unit=250, adu=2,
                 coverage_days_current=20, lead_time_days=10),
        ])

    def test_budget_prioritizes_stockout_and_preserves_demand(self):
        s = self._budget_suggestion()
        s.action_apply_budget()
        a = s.line_ids.filtered(lambda l: l.product_id == self.product_a)
        b = s.line_ids - a
        self.assertEqual((a.qty_final, b.qty_final), (10, 0))
        self.assertEqual(b.qty_suggested, 10)
        self.assertFalse(b.was_edited)
        self.assertEqual(s.budget_remaining, 0)

    def test_manual_priority_can_change_allocation(self):
        s = self._budget_suggestion()
        b = s.line_ids.filtered(lambda l: l.product_id == self.product_b)
        b.budget_priority = 'high'
        s.action_apply_budget()
        self.assertEqual(b.qty_final, 4)
        self.assertEqual((s.line_ids - b).qty_final, 0)

    def test_minimum_and_packaging_are_not_broken(self):
        s = self._budget_suggestion(700)
        self.product_a.seller_ids.min_qty = 6
        self.env['product.packaging'].create(dict(name='Pack 4',product_id=self.product_a.id,qty=4,purchase=True))
        s.action_apply_budget()
        a = s.line_ids.filtered(lambda l: l.product_id == self.product_a)
        self.assertEqual(a.qty_final, 0)
        self.assertEqual((s.line_ids - a).qty_final, 2)

    def test_purchase_uom_rounding_fits_budget(self):
        s = self._budget_suggestion(1100)
        self.product_a.uom_po_id = self.uom_dozen
        s.action_apply_budget()
        a = s.line_ids.filtered(lambda l: l.product_id == self.product_a)
        self.assertEqual(a.qty_final, 0)
        self.assertLessEqual(s.budget_used, 1100)

    def test_unknown_price_is_not_free_budget(self):
        s = self._budget_suggestion()
        s.line_ids[0].price_unit = 0
        s.action_apply_budget()
        self.assertEqual(s.line_ids[0].qty_final, 0)
        self.assertIn('precio', s.line_ids[0].budget_note.lower())
        s.line_ids[0].qty_final = 1
        with self.assertRaises(UserError):
            s.action_confirm()

    def test_over_budget_blocks_confirm_and_order_generation(self):
        s = self._budget_suggestion()
        with self.assertRaises(UserError):
            s.action_confirm()
        s.state = 'confirmed'
        with self.assertRaises(UserError):
            s.action_create_purchase_orders()
        self.assertFalse(s.purchase_order_ids)

    def test_edit_after_allocation_is_detected(self):
        s = self._budget_suggestion()
        s.action_apply_budget()
        b = s.line_ids.filtered(lambda l: l.product_id == self.product_b)
        b.qty_final = 1
        self.assertTrue(b.was_edited)
        with self.assertRaises(UserError):
            s.action_confirm()

    def test_reallocation_can_restore_automatic_quantities(self):
        s = self._budget_suggestion()
        s.action_apply_budget()
        s.budget_amount = 3500
        s.action_apply_budget()
        self.assertEqual(sum(s.line_ids.mapped('qty_final')), 20)
        self.assertFalse(any(s.line_ids.mapped('was_edited')))

    def test_zero_budget_and_negative_budget(self):
        s = self._budget_suggestion(0)
        s.action_apply_budget()
        self.assertEqual(s.budget_used, 0)
        self.assertFalse(any(s.line_ids.mapped('qty_final')))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            s.budget_amount = -1

    def test_legacy_prices_are_normalized(self):
        s = self._budget_suggestion(1000)
        a = s.line_ids.filtered(lambda l: l.product_id == self.product_a)
        self.product_a.uom_po_id = self.uom_dozen
        a.write(dict(price_in_stock_uom=False, price_unit=120, qty_suggested=120, qty_final=120))
        s.action_apply_budget()
        self.assertEqual(a.qty_final, 96)
        self.assertEqual(s.budget_used, 960)

    def test_order_confirmation_cannot_bypass_budget(self):
        s = self._budget_suggestion()
        s.action_apply_budget()
        s.action_confirm()
        s.action_create_purchase_orders()
        order = s.purchase_order_ids
        order.order_line.price_unit = 200
        with self.assertRaises(UserError):
            order.button_confirm()
        self.assertEqual(order.state, 'draft')

    def test_without_budget_preserves_existing_flow(self):
        s = self._budget_suggestion()
        s.budget_enabled = False
        s.action_confirm()
        s.action_create_purchase_orders()
        self.assertEqual(s.state, 'done')

    def test_recompute_does_not_preserve_automatic_budget_cuts_as_manual(self):
        s = self._budget_suggestion()
        metrics = {l.product_id.id: dict(qty_suggested=10,qty_final=10,price_unit=l.price_unit,
            supplier_id=l.supplier_id.id) for l in s.line_ids}
        s.action_apply_budget()
        s._apply_metrics(metrics)
        self.assertEqual(s.budget_used, 1000)
        self.assertFalse(any(s.line_ids.mapped('was_edited')))

    def test_confirmed_order_edits_cannot_exceed_budget(self):
        s = self._budget_suggestion()
        s.action_apply_budget()
        s.action_confirm()
        s.action_create_purchase_orders()
        order = s.purchase_order_ids
        order.button_confirm()
        with self.assertRaises(UserError):
            order.order_line.write({'price_unit': 200})
        self.assertEqual(order.order_line.price_unit, 100)

    def test_approval_checks_the_updated_budget(self):
        s = self._budget_suggestion()
        s.action_apply_budget()
        s.action_confirm()
        s.action_create_purchase_orders()
        order = s.purchase_order_ids
        order.state = 'to approve'
        order.order_line.price_unit = 200
        with self.assertRaises(UserError):
            order.button_approve()

    def test_fractional_unit_rounding_is_respected(self):
        s = self._budget_suggestion(280)
        self.uom_unit.rounding = .01
        s.action_apply_budget()
        a = s.line_ids.filtered(lambda l: l.product_id == self.product_a)
        self.assertAlmostEqual(a.qty_final, 2.8)

    def test_tax_does_not_consume_merchandise_budget(self):
        s = self._budget_suggestion()
        tax = self.env['account.tax'].create(dict(name='IVA prueba',amount=21,type_tax_use='purchase',company_id=self.company.id))
        self.product_a.supplier_taxes_id = tax
        s.action_apply_budget()
        s.action_confirm()
        s.action_create_purchase_orders()
        self.assertEqual(s.purchase_order_ids.amount_untaxed, 1000)
        self.assertEqual(s.purchase_order_ids.amount_total, 1210)

    def test_tax_included_price_uses_net_merchandise(self):
        s = self._budget_suggestion()
        tax = self.env['account.tax'].create(dict(name='IVA incluido prueba',amount=21,
            type_tax_use='purchase',company_id=self.company.id,price_include_override='tax_included'))
        self.product_a.supplier_taxes_id = tax
        s.line_ids.filtered(lambda l: l.product_id == self.product_a).price_unit = 121
        s.action_apply_budget()
        self.assertEqual(s.line_ids.filtered(lambda l: l.product_id == self.product_a).qty_final, 10)
        self.assertEqual(s.budget_used, 1000)
        s.action_confirm()
        s.action_create_purchase_orders()
        self.assertEqual(s.purchase_order_ids.amount_untaxed, 1000)

    def test_buyer_without_advisor_access_can_confirm_linked_order(self):
        s = self._budget_suggestion()
        s.action_apply_budget()
        s.action_confirm()
        s.action_create_purchase_orders()
        buyer = new_test_user(self.env,login='budget_buyer',groups='purchase.group_purchase_user',
                              company_id=self.company.id,company_ids=[Command.set(self.company.ids)])
        self.assertFalse(buyer.has_group('prometeo_purchase_advisor.group_purchase_advisor_user'))
        order = s.purchase_order_ids.with_user(buyer)
        order.button_confirm()
        self.assertEqual(order.state, 'purchase')

    def test_supplier_minimum_from_another_company_is_respected(self):
        s = self._budget_suggestion(500)
        other = self.env['res.company'].create({'name':'Tarifa central presupuesto'})
        self.product_a.seller_ids.write({'company_id':other.id,'min_qty':6})
        s = s.with_context(allowed_company_ids=[self.company.id,other.id])
        s.action_apply_budget()
        self.assertEqual(s.line_ids.filtered(lambda l: l.product_id == self.product_a).qty_final, 0)

    def test_automatic_recompute_preserves_real_manual_quantity(self):
        s = self._budget_suggestion(1000)
        s.action_apply_budget()
        b = s.line_ids.filtered(lambda l: l.product_id == self.product_b)
        b.qty_final = 2
        metrics = {l.product_id.id: dict(qty_suggested=10,qty_final=10,price_unit=l.price_unit,
            supplier_id=l.supplier_id.id) for l in s.line_ids}
        s._apply_metrics(metrics)
        self.assertEqual(b.qty_final, 2)
        self.assertTrue(b.was_edited)
        self.assertEqual((s.line_ids - b).qty_final, 5)

    def test_form_manual_line_survives_repeated_budget_adjustments(self):
        self.product_a.supplier_taxes_id = False
        s = self._make_suggestion(budget_enabled=True, budget_amount=1000)
        with Form(s) as form:
            with form.line_ids.new() as line:
                line.product_id = self.product_a
                line.qty_final = 20
        self.assertTrue(s.line_ids.is_manual)
        s.action_apply_budget()
        self.assertEqual(s.line_ids.qty_final, 10)
        s.action_apply_budget()
        self.assertEqual(s.line_ids.qty_final, 10)
