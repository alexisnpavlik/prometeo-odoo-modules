from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import PurchaseAdvisorCommon


@tagged('post_install', '-at_install')
class TestTransfers(PurchaseAdvisorCommon):
    def _transfer_case(self, stock=200, demand=2):
        """Destino con demanda de 81 unidades y origen con stock físico."""
        _company, branch = self._isolated_company('Destino traslado')
        self._sell_daily(self.product_a, demand, 31, 1, warehouse=branch)
        if stock:
            self._set_stock(self.product_a, stock)
        suggestion = self._make_suggestion(
            warehouse_id=branch.id, prioritize_transfers=True,
            source_warehouse_ids=[Command.set(self.warehouse.ids)])
        return suggestion.with_context(allowed_company_ids=(self.company | branch.company_id).ids), branch

    def test_transfer_covers_need_without_purchase(self):
        suggestion, branch = self._transfer_case()
        suggestion.action_compute()
        self.assertEqual(suggestion.line_ids.qty_suggested, 0)
        self.assertEqual(suggestion.transfer_plan_ids.quantity, 81)
        self.assertEqual(suggestion.transfer_plan_ids.source_warehouse_id, self.warehouse)
        self.assertEqual(suggestion.transfer_plan_ids.destination_warehouse_id, branch)
        suggestion.action_confirm()
        with self.assertRaises(UserError):
            suggestion.action_create_purchase_orders()

    def test_only_uncovered_need_is_purchased(self):
        suggestion, _branch = self._transfer_case(stock=20)
        suggestion.action_compute()
        self.assertEqual(suggestion.transfer_plan_ids.quantity, 20)
        self.assertEqual(suggestion.line_ids.qty_suggested, 61)

    def test_source_keeps_its_own_coverage_and_safety(self):
        suggestion, _branch = self._transfer_case(stock=100)
        self._sell_daily(self.product_a, 2, 31, 1)
        suggestion.action_compute()
        self.assertEqual(suggestion.transfer_plan_ids.quantity, 19)
        self.assertEqual(suggestion.line_ids.qty_suggested, 62)

    def test_future_receipt_is_not_transferable_stock(self):
        suggestion, _branch = self._transfer_case(stock=0)
        move = self.env['stock.move'].create({
            'name': 'Entrada futura', 'product_id': self.product_a.id,
            'product_uom_qty': 100, 'product_uom': self.product_a.uom_id.id,
            'company_id': self.company.id, 'location_id': self.supplier_location.id,
            'location_dest_id': self.warehouse.lot_stock_id.id,
        })
        move._action_confirm()
        suggestion.action_compute()
        self.assertFalse(suggestion.transfer_plan_ids)
        self.assertEqual(suggestion.line_ids.qty_suggested, 81)

    def test_prepare_intercompany_and_recalculate_without_duplicate(self):
        suggestion, branch = self._transfer_case(stock=100)
        suggestion.action_compute()
        suggestion.action_prepare_transfers()
        plans = suggestion.transfer_plan_ids
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans.picking_id.state, 'assigned')
        self.assertEqual(plans.receipt_id.location_dest_id, branch.lot_stock_id)
        self.assertEqual(plans.receipt_id.move_ids.move_orig_ids, plans.picking_id.move_ids)
        self.assertFalse(plans.picking_id.partner_id)
        self.assertTrue(suggestion.transfer_recompute_required)
        with self.assertRaises(UserError):
            suggestion.action_prepare_transfers()
        suggestion.action_compute()
        self.assertFalse(suggestion.transfer_recompute_required)
        self.assertEqual(len(suggestion.transfer_plan_ids), 1)
        self.assertEqual(suggestion.line_ids.qty_suggested, 0)
        self.assertEqual(len(suggestion.transfer_picking_ids), 2)
        suggestion.action_finish_transfers()
        self.assertEqual(suggestion.state, 'done')
        self.assertFalse(suggestion.purchase_order_ids)

    def test_changed_stock_blocks_preparation_atomically(self):
        suggestion, _branch = self._transfer_case(stock=100)
        suggestion.action_compute()
        self._set_stock(self.product_a, -95)
        with self.assertRaises(UserError):
            suggestion.action_prepare_transfers()
        self.assertFalse(suggestion.transfer_plan_ids.picking_id)

    def test_cancelled_transfer_blocks_stale_purchase_and_allows_replacement(self):
        suggestion, _branch = self._transfer_case(stock=100)
        suggestion.action_compute()
        suggestion.action_prepare_transfers()
        suggestion.action_compute()
        suggestion.transfer_plan_ids.picking_id.action_cancel()
        with self.assertRaisesRegex(UserError, 'cambiaron'):
            suggestion._lines_to_order()
        suggestion.action_compute()
        suggestion.action_prepare_transfers()
        suggestion.action_compute()
        suggestion.action_finish_transfers()
        self.assertEqual(suggestion.state, 'done')

    def test_operator_reads_prepared_status_but_cannot_prepare_inventory(self):
        suggestion, branch = self._transfer_case()
        suggestion.action_compute()
        operator = new_test_user(self.env, login='transfer_reader',
            groups='base.group_user,prometeo_purchase_advisor.group_purchase_advisor_user',
            company_id=self.company.id,
            company_ids=[Command.set((self.company | branch.company_id).ids)])
        restricted = suggestion.with_user(operator)
        with self.assertRaises(AccessError):
            restricted.action_prepare_transfers()
        suggestion.action_prepare_transfers()
        self.assertEqual(restricted.transfer_plan_ids.read(['state'])[0]['state'], 'prepared')
        self.assertEqual(restricted.transfer_picking_count, 2)
        with self.assertRaises(AccessError):
            restricted.transfer_plan_ids.write({'receipt_id': suggestion.transfer_plan_ids.receipt_id.id})
        with self.assertRaises(AccessError):
            restricted.transfer_plan_ids.copy({'picking_id': suggestion.transfer_plan_ids.picking_id.id})
        with self.assertRaises(AccessError):
            restricted.transfer_plan_ids.with_context(
                default_receipt_id=suggestion.transfer_plan_ids.receipt_id.id).copy()
        transient = restricted.transfer_plan_ids.new({'picking_id': suggestion.transfer_plan_ids.picking_id.id})
        self.assertEqual(transient.state, 'proposed')
        self.assertFalse(transient._linked_pickings())
        suggestion.source_warehouse_ids = [Command.clear()]
        restricted = restricted.with_context(allowed_company_ids=branch.company_id.ids)
        self.assertFalse(restricted.search([('id', '=', suggestion.id)]))

    def test_same_company_transfer_uses_one_picking(self):
        warehouse = self.env['stock.warehouse'].create({
            'name': 'Destino misma compañía', 'code': 'DSTTR', 'company_id': self.company.id})
        self._sell_daily(self.product_a, 2, 31, 1, warehouse=warehouse)
        self._set_stock(self.product_a, 100)
        suggestion = self._make_suggestion(warehouse_id=warehouse.id,
            prioritize_transfers=True, source_warehouse_ids=[Command.set(self.warehouse.ids)])
        suggestion.action_compute()
        suggestion.action_prepare_transfers()
        self.assertEqual(len(suggestion.transfer_picking_ids), 1)
        self.assertEqual(suggestion.transfer_plan_ids.picking_id.location_dest_id, warehouse.lot_stock_id)

    def test_stock_is_allocated_once_across_destinations(self):
        suggestion, a = self._transfer_case(stock=100)
        _company, b = self._isolated_company('Segundo destino traslado')
        self._sell_daily(self.product_a, 2, 31, 1, warehouse=b)
        suggestion = suggestion.with_context(allowed_company_ids=(self.company | a.company_id | b.company_id).ids)
        suggestion.write({'supply_mode': 'centralized', 'demand_warehouse_ids': [Command.set(b.ids)]})
        suggestion.action_compute()
        self.assertEqual(sum(suggestion.transfer_plan_ids.mapped('quantity')), 100)
        self.assertEqual(suggestion.line_ids.qty_suggested, 62)

    def test_intercompany_delivery_uses_explicit_receipt_without_extra_counterpart(self):
        suggestion, branch = self._transfer_case(stock=100)
        suggestion.action_compute()
        suggestion.action_prepare_transfers()
        plan = suggestion.transfer_plan_ids
        picking_count = self.env['stock.picking'].search_count([])
        plan.picking_id.move_ids.write({'quantity': 81, 'picked': True})
        plan.picking_id._action_done()
        self.assertEqual(self.env['stock.picking'].search_count([]), picking_count)
        self.assertEqual(plan.receipt_id.state, 'assigned')
        plan.receipt_id.move_ids.write({'quantity': 81, 'picked': True})
        plan.receipt_id._action_done()
        self.assertEqual(plan.state, 'done')
        self.assertEqual(self.product_a.with_context(warehouse_id=branch.id).qty_available, 81)
        self.assertEqual(self.product_a.with_context(warehouse_id=self.warehouse.id).qty_available, 19)

    def test_transfer_without_supplier_still_resolves_need(self):
        suggestion, _branch = self._transfer_case(stock=100)
        self.product_a.seller_ids.unlink()
        suggestion.action_compute()
        self.assertFalse(suggestion.line_ids.supplier_id)
        self.assertEqual(suggestion.line_ids.qty_suggested, 0)
        self.assertGreater(suggestion.transfer_plan_ids.quantity, 0)
        suggestion.action_prepare_transfers()
        suggestion.action_compute()
        suggestion.action_finish_transfers()
        self.assertFalse(suggestion.purchase_order_ids)

    def test_changed_transfer_uom_requires_recalculation(self):
        suggestion, _branch = self._transfer_case(stock=100)
        suggestion.action_compute()
        suggestion.action_prepare_transfers()
        suggestion.action_compute()
        suggestion.transfer_plan_ids.receipt_id.move_ids.product_uom = self.env.ref('uom.product_uom_dozen')
        with self.assertRaisesRegex(UserError, 'cambiaron'):
            suggestion._lines_to_order()

    def test_existing_calculation_must_search_surplus_before_purchase(self):
        suggestion = self._make_suggestion(prioritize_transfers=True, lines=[{
            'product_id': self.product_a.id, 'supplier_id': self.supplier_a.id,
            'qty_final': 10, 'qty_suggested': 10,
        }])
        suggestion.state = 'computed'
        with self.assertRaisesRegex(UserError, 'buscar excedentes'):
            suggestion.action_confirm()
        suggestion.state = 'confirmed'
        with self.assertRaisesRegex(UserError, 'buscar excedentes'):
            suggestion.action_create_purchase_orders()
        self.assertFalse(suggestion.purchase_order_ids)

    def test_reserved_stock_is_not_reused(self):
        suggestion, _branch = self._transfer_case(stock=100)
        move = self.env['stock.move'].create({
            'name': 'Salida comprometida', 'product_id': self.product_a.id,
            'product_uom_qty': 90, 'product_uom': self.product_a.uom_id.id,
            'company_id': self.company.id, 'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.customer_location.id,
        })
        move._action_confirm()
        move._action_assign()
        suggestion.action_compute()
        self.assertEqual(suggestion.transfer_plan_ids.quantity, 10)
        self.assertEqual(suggestion.line_ids.qty_suggested, 71)

    def test_rounding_need_before_transfer_avoids_tiny_purchase(self):
        suggestion, _branch = self._transfer_case(stock=100, demand=0.51)
        suggestion.action_compute()
        self.assertEqual(suggestion.line_ids.qty_suggested, 0)
        self.assertGreater(suggestion.transfer_plan_ids.quantity, 20.65)
