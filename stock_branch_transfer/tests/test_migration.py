from odoo.tests import tagged

from .common import BranchTransferCommon


@tagged("post_install", "-at_install")
class TestMigration(BranchTransferCommon):
    """Migración de recepciones pendientes de stock_intercompany."""

    def setUp(self):
        super().setUp()
        if "counterpart_of_picking_id" not in self.env["stock.picking"]._fields:
            self.skipTest("stock_intercompany no está instalado")
        self.set_stock(self.product, self.company_a, 50.0)
        self.old_transit = self.env.ref("stock.stock_location_inter_company")
        warehouse_a = self.env["stock.warehouse"].search([("company_id", "=", self.company_a.id)], limit=1)
        out = self.env["stock.picking"].with_company(self.company_a).create({
            "picking_type_id": warehouse_a.out_type_id.id,
            "partner_id": self.company_b.partner_id.id,
            "location_id": warehouse_a.lot_stock_id.id,
            "location_dest_id": self.old_transit.id,
            "company_id": self.company_a.id,
            "move_ids": [(0, 0, {
                "name": "viejo",
                "product_id": self.product.id,
                "product_uom": self.product.uom_id.id,
                "product_uom_qty": 10.0,
                "location_id": warehouse_a.lot_stock_id.id,
                "location_dest_id": self.old_transit.id,
                "company_id": self.company_a.id,
            })],
        })
        out.action_confirm()
        out.move_ids.quantity = 10.0
        out.move_ids.picked = True
        out._action_done()
        self.out = out
        self.receipt = self.env["stock.picking"].sudo().search([("counterpart_of_picking_id", "=", out.id)])
        self.assertTrue(self.receipt, "stock_intercompany no generó la recepción vieja")

    def test_migrates_pending_receipt(self):
        old_transit_before = self._qty_at(self.product, self.old_transit)
        transfers = self.env["stock.branch.transfer"].migrate_from_stock_intercompany()
        self.assertEqual(len(transfers), 1)
        transfer = transfers
        self.assertEqual(transfer.state, "in_transit")
        self.assertEqual(transfer.company_id, self.company_a)
        self.assertEqual(transfer.dest_company_id, self.company_b)
        self.assertEqual(transfer.line_ids.qty_sent, 10.0)
        self.assertEqual(transfer.legacy_receipt_id, self.receipt)
        self.assertEqual(self.receipt.state, "cancel")
        self.assertEqual(self.qty(self.product, self.company_a), 40.0)
        self.assertEqual(self.transit_qty(self.product), 10.0)
        self.assertEqual(self._qty_at(self.product, self.old_transit), old_transit_before - 10.0)
        transfer.with_user(self.user_b).with_company(self.company_b).action_receive()
        self.assertEqual(self.qty(self.product, self.company_a), 40.0)
        self.assertEqual(self.qty(self.product, self.company_b), 10.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)

    def test_migration_is_idempotent(self):
        Transfer = self.env["stock.branch.transfer"]
        Transfer.migrate_from_stock_intercompany()
        self.assertFalse(Transfer.migrate_from_stock_intercompany())

    def test_cancel_migrated_returns_to_origin(self):
        transfer = self.env["stock.branch.transfer"].migrate_from_stock_intercompany()
        transfer.with_user(self.manager).action_cancel()
        self.assertEqual(self.qty(self.product, self.company_a), 50.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)
