from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BranchTransferCommon


class TestTransferFlow(BranchTransferCommon):

    def setUp(self):
        super().setUp()
        self.set_stock(self.product, self.company_a, 50.0)

    def _send(self, qty=10.0, user=None, dest=None):
        user = user or self.user_a
        transfer = self.make_transfer(user, qty=qty, dest=dest)
        transfer.with_user(user).with_company(user.company_id).action_send()
        return transfer

    def _receive_diff(self, transfer, user, quantities, extra=None, note="Faltó"):
        """Recibe con diferencias: quantities = {product: qty_recibida}, extra = {product: qty} no enviados."""
        action = transfer.with_user(user).action_open_receive_diff()
        wizard = self.env[action["res_model"]].with_user(user).with_context(action["context"]).create({"note": note})
        for line in wizard.line_ids:
            line.qty_received = quantities.get(line.product_id, line.qty_received)
        for product, qty in (extra or {}).items():
            wizard.line_ids = [(0, 0, {"product_id": product.id, "qty_received": qty})]
        wizard.action_confirm()

    def test_send_moves_to_transit(self):
        transfer = self._send()
        self.assertEqual(transfer.state, "in_transit")
        self.assertEqual(self.qty(self.product, self.company_a), 40.0)
        self.assertEqual(self.transit_qty(self.product), 10.0)
        self.assertEqual(self.qty(self.product, self.company_b), 0.0)
        self.assertTrue(transfer.date_sent)

    def test_receive_full(self):
        transfer = self._send()
        transfer.with_user(self.user_b).action_receive()
        self.assertEqual(transfer.state, "received")
        self.assertEqual(transfer.line_ids.qty_received, 10.0)
        self.assertEqual(self.qty(self.product, self.company_a), 40.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)
        self.assertEqual(self.qty(self.product, self.company_b), 10.0)

    def test_receive_with_shortage_then_close(self):
        transfer = self._send()
        self._receive_diff(transfer, self.user_b, {self.product: 8.0})
        self.assertEqual(transfer.state, "with_diff")
        self.assertEqual(transfer.diff_note, "Faltó")
        self.assertEqual(self.qty(self.product, self.company_b), 8.0)
        self.assertEqual(self.transit_qty(self.product), 2.0)
        transfer.with_user(self.manager).action_close()
        self.assertEqual(transfer.state, "closed")
        self.assertEqual(self.qty(self.product, self.company_a), 42.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)
        self.assertEqual(self.qty(self.product, self.company_b), 8.0)

    def test_receive_with_excess(self):
        transfer = self._send()
        self._receive_diff(transfer, self.user_b, {self.product: 12.0})
        self.assertEqual(transfer.state, "with_diff")
        self.assertEqual(self.qty(self.product, self.company_a), 38.0)
        self.assertEqual(self.transit_qty(self.product), 0.0)
        self.assertEqual(self.qty(self.product, self.company_b), 12.0)

    def test_receive_unsent_product(self):
        transfer = self._send()
        self._receive_diff(transfer, self.user_b, {}, extra={self.product2: 3.0})
        self.assertEqual(self.qty(self.product2, self.company_a), -3.0)
        self.assertEqual(self.qty(self.product2, self.company_b), 3.0)
        self.assertEqual(self.transit_qty(self.product2), 0.0)
        self.assertEqual(self.qty(self.product, self.company_b), 10.0)

    def test_receive_diff_matching_is_received(self):
        transfer = self._send()
        self._receive_diff(transfer, self.user_b, {})
        self.assertEqual(transfer.state, "received")

    def test_user_a_cannot_receive(self):
        transfer = self._send()
        with self.assertRaises(UserError):
            transfer.with_user(self.user_a).action_receive()
        self.assertEqual(transfer.state, "in_transit")

    def test_non_manager_cannot_close(self):
        transfer = self._send()
        self._receive_diff(transfer, self.user_b, {self.product: 8.0})
        with self.assertRaises(UserError):
            transfer.with_user(self.user_b).action_close()

    def test_multi_company_user_receives(self):
        user_ab = self._make_user("sbt_user_ab", self.company_a, self.company_a | self.company_b)
        self.set_stock(self.product, self.company_c, 5.0)
        transfer = self._send(qty=5.0, user=self.user_c)
        transfer.with_user(user_ab).with_company(self.company_a).action_receive()
        self.assertEqual(self.qty(self.product, self.company_b), 5.0)

    def test_wrong_state_actions(self):
        transfer = self.make_transfer(self.user_a)
        with self.assertRaises(UserError):
            transfer.with_user(self.user_b).action_receive()
        transfer.with_user(self.user_a).action_send()
        pickings = len(transfer.sudo().picking_ids)
        with self.assertRaises(UserError):
            transfer.with_user(self.user_a).action_send()
        self.assertEqual(len(transfer.sudo().picking_ids), pickings)

    def test_send_without_quantities_fails(self):
        transfer = self.make_transfer(self.user_a, qty=0.0)
        with self.assertRaises(UserError):
            transfer.with_user(self.user_a).action_send()

    def test_pending_count(self):
        Transfer = self.env["stock.branch.transfer"]
        transfer = self._send()
        self.assertEqual(Transfer.with_user(self.user_b).get_pending_count(), 1)
        self.assertEqual(Transfer.with_user(self.user_a).get_pending_count(), 0)
        self._receive_diff(transfer, self.user_b, {self.product: 8.0})
        self.assertEqual(Transfer.with_user(self.user_a).get_pending_count(), 1)
        self.assertEqual(Transfer.with_user(self.user_b).get_pending_count(), 1)
        transfer.with_user(self.manager).action_close()
        self.assertEqual(Transfer.with_user(self.user_b).get_pending_count(), 0)


    def test_pending_counts_by_menu(self):
        Transfer = self.env["stock.branch.transfer"]
        transfer = self._send()
        self.assertEqual(Transfer.with_user(self.user_b).get_pending_counts(),
                         {"total": 1, "incoming": 1, "sent": 0})
        self.assertEqual(Transfer.with_user(self.user_a).get_pending_counts(),
                         {"total": 0, "incoming": 0, "sent": 0})
        self._receive_diff(transfer, self.user_b, {self.product: 8.0})
        self.assertEqual(Transfer.with_user(self.user_a).get_pending_counts(),
                         {"total": 1, "incoming": 0, "sent": 1})
        self.assertEqual(Transfer.with_user(self.user_b).get_pending_counts(),
                         {"total": 1, "incoming": 1, "sent": 0})


@tagged("post_install", "-at_install")
class TestTransferIntercompany(BranchTransferCommon):
    """Corre después de cargar todos los módulos, para que stock_intercompany esté en el registro."""

    def test_no_intercompany_counterpart(self):
        if "counterpart_of_picking_id" not in self.env["stock.picking"]._fields:
            self.skipTest("stock_intercompany no está instalado")
        self.set_stock(self.product, self.company_a, 50.0)
        transfer = self.make_transfer(self.user_a)
        transfer.with_user(self.user_a).with_company(self.company_a).action_send()
        transfer.with_user(self.user_b).with_company(self.company_b).action_receive()
        count = self.env["stock.picking"].sudo().search_count(
            [("counterpart_of_picking_id", "in", transfer.picking_ids.ids)]
        )
        self.assertEqual(count, 0)
        self.assertEqual(self.qty(self.product, self.company_b), 10.0)
