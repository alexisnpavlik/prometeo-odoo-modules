from datetime import timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestSupplyNetwork(PurchaseAdvisorCommon):
    """Compra central sin duplicar demanda, stock ni mínimos del proveedor."""

    def _network(self):
        """Dos sucursales de compañías distintas que venden el mismo producto."""
        _company_a, branch_a = self._isolated_company("Sucursal red A")
        _company_b, branch_b = self._isolated_company("Sucursal red B")
        self._sell_daily(self.product_a, 2, 31, 1, warehouse=branch_a)
        self._sell_daily(self.product_a, 4, 31, 1, warehouse=branch_b)
        self._set_stock(self.product_a, 20)
        suggestion = self._make_suggestion(
            supply_mode="centralized",
            demand_warehouse_ids=[Command.set((branch_a | branch_b).ids)],
        )
        return suggestion, branch_a, branch_b

    def test_central_buys_branch_demand_using_its_stock_once(self):
        suggestion, _a, _b = self._network()
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(lambda line: line.product_id == self.product_a)
        self.assertEqual(line.adu, 6)
        self.assertEqual(line.qty_suggested, 223)  # (2+4)*40 + 3 de seguridad - 20
        suggestion.action_confirm()
        suggestion.action_create_purchase_orders()
        self.assertEqual(suggestion.purchase_order_ids.company_id, self.company)
        self.assertEqual(suggestion.purchase_order_ids.picking_type_id, self.warehouse.in_type_id)

    def test_centralized_calculation_includes_product_without_supplier(self):
        """Consolida demanda de sucursales aunque falte completar el proveedor."""
        suggestion, a, b = self._network()
        self._sell_daily(self.product_no_seller, 2, 31, 1, warehouse=a)
        self._sell_daily(self.product_no_seller, 3, 31, 1, warehouse=b)
        suggestion.action_compute()
        line = suggestion.line_ids.filtered(lambda row: row.product_id == self.product_no_seller)
        self.assertEqual(len(line), 1)
        self.assertGreater(line.qty_suggested, 0)
        self.assertFalse(line.supplier_id)
        self.assertIn("Sin proveedor", line.warnings)

    def test_branch_surplus_is_not_assumed_available_to_other_branches(self):
        suggestion, _a, b = self._network()
        self._set_stock(self.product_a, 1000, location=b.lot_stock_id)
        suggestion.action_compute()
        self.assertEqual(suggestion.line_ids.qty_suggested, 61)  # A necesita 81, central tiene 20

    def test_direct_purchase_does_not_take_other_branch_demand(self):
        suggestion, a, _b = self._network()
        direct = self._make_suggestion(warehouse_id=a.id)
        direct.action_compute()
        self.assertEqual(direct.line_ids.qty_suggested, 81)

    def test_branch_confirmed_receipt_reduces_central_purchase(self):
        suggestion, a, _b = self._network()
        move = self.env["stock.move"].create({
            "name": "Compra directa pendiente", "product_id": self.product_a.id,
            "product_uom_qty": 60, "product_uom": self.product_a.uom_id.id,
            "company_id": a.company_id.id, "location_id": self.supplier_location.id,
            "location_dest_id": a.lot_stock_id.id,
        })
        move._action_confirm()
        suggestion.action_compute()
        self.assertEqual(suggestion.line_ids.qty_suggested, 163)

    def test_supplier_minimum_is_applied_once_to_consolidated_order(self):
        suggestion, _a, _b = self._network()
        self.product_a.seller_ids.min_qty = 300
        suggestion.action_compute()
        self.assertEqual(suggestion.line_ids.qty_suggested, 300)

    def test_transfer_time_is_added_for_branch_coverage(self):
        suggestion, _a, _b = self._network()
        suggestion.transfer_days = 3
        suggestion.action_compute()
        self.assertEqual(suggestion.line_ids.qty_suggested, 241)

    def test_centralized_requires_branches(self):
        suggestion = self._make_suggestion(supply_mode="centralized")
        with self.assertRaises(UserError):
            suggestion.action_compute()

    def test_detect_branches_from_intercompany_dispatch_partner(self):
        _company, branch = self._isolated_company("Destino detectado")
        picking = self.env["stock.picking"].create({
            "partner_id": branch.company_id.partner_id.id,
            "picking_type_id": self.warehouse.out_type_id.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "location_dest_id": self.env.ref("stock.stock_location_inter_company").id,
        })
        move = self._make_move(self.product_a, 10, self._today() - timedelta(days=2))
        move.write({"picking_id": picking.id, "location_dest_id": picking.location_dest_id.id})
        suggestion = self._make_suggestion(supply_mode="centralized")
        suggestion.action_detect_demand_warehouses()
        self.assertEqual(suggestion.demand_warehouse_ids, branch)

    def test_negative_transfer_time_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_suggestion(transfer_days=-1)

    def test_pending_dispatch_does_not_create_extra_network_demand(self):
        suggestion, a, _b = self._network()
        picking = self.env["stock.picking"].create({
            "partner_id": a.company_id.partner_id.id,
            "picking_type_id": self.warehouse.out_type_id.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "location_dest_id": self.env.ref("stock.stock_location_inter_company").id,
        })
        self.env["stock.move"].create({
            "name": "Traslado preparado", "picking_id": picking.id,
            "product_id": self.product_a.id, "product_uom_qty": 60,
            "product_uom": self.product_a.uom_id.id,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
        })._action_confirm()
        suggestion.action_compute()
        self.assertEqual(suggestion.line_ids.qty_suggested, 223)

    def test_branch_model_is_resolved_in_its_company(self):
        suggestion, a, _b = self._network()
        branch_model = self._make_model(company_id=a.company_id.id, service_level=0.9)
        a.company_id.suggestion_demand_model_id = branch_model
        suggestion.action_compute()
        rows = suggestion.line_ids.params_snapshot["warehouses"]
        branch = next(row for row in rows if row["warehouse_id"] == a.id)
        self.assertEqual(branch["parameters"]["service_level"], 0.9)

    def test_central_only_user_cannot_read_branch_metrics(self):
        suggestion, _a, _b = self._network()
        suggestion.action_compute()
        operator = new_test_user(
            self.env, login="central_only_advisor", company_id=self.company.id,
            company_ids=[Command.set(self.company.ids)],
            groups="base.group_user,stock.group_stock_user,prometeo_purchase_advisor.group_purchase_advisor_user")
        restricted = suggestion.with_user(operator).with_context(allowed_company_ids=self.company.ids)
        self.assertFalse(restricted.search([("id", "=", suggestion.id)]))
        with self.assertRaises(AccessError):
            restricted.read(["total_amount"])
        with self.assertRaises(AccessError):
            suggestion.line_ids.with_user(operator).with_context(
                allowed_company_ids=self.company.ids).read(["params_snapshot"])
        suggestion.action_draft()
        suggestion.demand_warehouse_ids = [Command.clear()]
        self.assertFalse(restricted.search([("id", "=", suggestion.id)]),
                         "Quitar sucursales no debe liberar métricas que siguen guardadas")
        new_warehouse = self.env["stock.warehouse"].create({
            "name": "Nueva sucursal privada", "code": "NSP",
            "company_id": _a.company_id.id,
        })
        new_suggestion = self._make_suggestion(
            supply_mode="centralized", demand_warehouse_ids=[Command.set(new_warehouse.ids)])
        self.assertFalse(restricted.search([("id", "=", new_suggestion.id)]),
                         "La caché de permisos no debe omitir almacenes nuevos")

    def test_operator_can_read_authorized_suggestions_and_lines(self):
        """La lectura del listado web evalúa permisos después de buscar registros."""
        suggestion = self._make_suggestion(lines=[{
            "product_id": self.product_a.id,
            "supplier_id": self.supplier_a.id,
            "qty_suggested": 2,
        }])
        operator = new_test_user(
            self.env, login="advisor_read_operator", company_id=self.company.id,
            company_ids=[Command.set(self.company.ids)],
            groups="base.group_user,stock.group_stock_user,prometeo_purchase_advisor.group_purchase_advisor_user")
        restricted = suggestion.with_user(operator).with_context(
            allowed_company_ids=self.company.ids)
        result = restricted.web_search_read(
            [("id", "=", suggestion.id)], {"name": {}, "total_amount": {}})
        self.assertEqual(result["length"], 1)
        self.assertEqual(result["records"][0]["id"], suggestion.id)
        self.assertEqual(restricted.read(["name"])[0]["id"], suggestion.id)
        lines = suggestion.line_ids.with_user(operator).with_context(
            allowed_company_ids=self.company.ids).read(["qty_suggested"])
        self.assertEqual(len(lines), 1)

    def test_authorized_network_read_tracks_selected_companies(self):
        """Cambiar compañías no reutiliza un permiso calculado con otro alcance."""
        suggestion, a, b = self._network()
        suggestion.action_compute()
        companies = self.company | a.company_id | b.company_id
        operator = new_test_user(
            self.env, login="advisor_network_reader", company_id=self.company.id,
            company_ids=[Command.set(companies.ids)],
            groups="base.group_user,stock.group_stock_user,prometeo_purchase_advisor.group_purchase_advisor_user")
        allowed = suggestion.with_user(operator).with_context(allowed_company_ids=companies.ids)
        self.assertEqual(allowed.read(["total_amount"])[0]["id"], suggestion.id)
        self.assertTrue(allowed.line_ids.read(["params_snapshot"]))
        restricted = allowed.with_context(allowed_company_ids=self.company.ids)
        self.assertFalse(restricted.search([("id", "=", suggestion.id)]))
        with self.assertRaises(AccessError):
            restricted.read(["total_amount"])
        self.assertEqual(allowed.read(["total_amount"])[0]["id"], suggestion.id)
