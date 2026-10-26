from odoo.exceptions import UserError

from .common import BranchTransferCommon


class TestTransferManager(BranchTransferCommon):

    def setUp(self):
        super().setUp()
        self.set_stock(self.product, self.company_a, 50.0)
        self.transfer = self.make_transfer(self.user_a)
        self.transfer.with_user(self.user_a).action_send()

    def _as_manager(self):
        return self.transfer.with_user(self.manager)

    def test_manager_edits_in_transit(self):
        self._as_manager().line_ids.qty_sent = 6.0
        self.assertEqual(self.transfer.state, "in_transit")
        self.assertEqual(self.qty(self.product, self.company_a), 44.0)
        self.assertEqual(self.transit_qty(self.product), 6.0)

    def test_manager_edits_after_received(self):
        self.transfer.with_user(self.user_b).action_receive()
        self._as_manager().line_ids.qty_received = 7.0
        self.assertEqual(self.transfer.state, "received")
        self.assertEqual(self.qty(self.product, self.company_a), 43.0)
        self.assertEqual(self.qty(self.product, self.company_b), 7.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)

    def test_manager_changes_dest_after_received(self):
        self.transfer.with_user(self.user_b).action_receive()
        self._as_manager().dest_company_id = self.company_c
        self.assertEqual(self.qty(self.product, self.company_b), 0.0)
        self.assertEqual(self.qty(self.product, self.company_c), 10.0)
        self.assertEqual(self.qty(self.product, self.company_a), 40.0)

    def test_manager_adds_line_in_transit(self):
        self._as_manager().line_ids = [(0, 0, {"product_id": self.product2.id, "qty_sent": 4.0})]
        self.assertEqual(self.qty(self.product2, self.company_a), -4.0)
        self.assertEqual(self.transit_qty(self.product2), 4.0)

    def test_manager_removes_line_in_transit(self):
        self._as_manager().line_ids.unlink()
        self.assertEqual(self.qty(self.product, self.company_a), 50.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)

    def test_manager_edits_with_diff_then_close(self):
        action = self.transfer.with_user(self.user_b).action_open_receive_diff()
        wizard = self.env[action["res_model"]].with_user(self.user_b).with_context(action["context"]).create({})
        wizard.line_ids.qty_received = 8.0
        wizard.action_confirm()
        self._as_manager().line_ids.qty_received = 9.0
        self._as_manager().action_close()
        self.assertEqual(self.transfer.state, "closed")
        self.assertEqual(self.qty(self.product, self.company_a), 41.0)
        self.assertEqual(self.qty(self.product, self.company_b), 9.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)

    def test_cancel_reverts_all(self):
        self.transfer.with_user(self.user_b).action_receive()
        done_before = self.transfer.picking_ids.filtered(lambda p: p.state == "done")
        self._as_manager().action_cancel()
        self.assertEqual(self.transfer.state, "cancel")
        self.assertEqual(self.qty(self.product, self.company_a), 50.0)
        self.assertEqual(self.qty(self.product, self.company_b), 0.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)
        self.assertTrue(all(p.state == "done" for p in done_before))

    def test_user_cannot_cancel(self):
        with self.assertRaises(UserError):
            self.transfer.with_user(self.user_a).action_cancel()

    def test_user_cannot_edit_sent(self):
        with self.assertRaises(UserError):
            self.transfer.with_user(self.user_a).line_ids.qty_sent = 5.0
        with self.assertRaises(UserError):
            self.transfer.with_user(self.user_a).dest_company_id = self.company_c

    def test_unlink_sent_blocked(self):
        with self.assertRaises(UserError):
            self._as_manager().unlink()
