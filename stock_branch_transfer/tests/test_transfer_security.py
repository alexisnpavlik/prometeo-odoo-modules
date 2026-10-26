from odoo.exceptions import UserError

from .common import BranchTransferCommon


class TestTransferSecurity(BranchTransferCommon):
    """Escrituras directas por RPC que saltean los botones."""

    def setUp(self):
        super().setUp()
        self.set_stock(self.product, self.company_a, 50.0)
        self.transfer = self.make_transfer(self.user_a)
        self.transfer.with_user(self.user_a).action_send()

    def test_forged_context_ignored(self):
        forged = self.transfer.with_user(self.user_a).with_context(branch_transfer_internal=True)
        with self.assertRaises(UserError):
            forged.line_ids.qty_sent = 1.0
        with self.assertRaises(UserError):
            forged.write({"dest_company_id": self.company_c.id})

    def test_user_cannot_write_state(self):
        for state in ("draft", "closed", "cancel"):
            with self.assertRaises(UserError):
                self.transfer.with_user(self.user_a).write({"state": state})
        self.assertEqual(self.transfer.state, "in_transit")

    def test_manager_cannot_write_state_directly(self):
        with self.assertRaises(UserError):
            self.transfer.with_user(self.manager).write({"state": "closed"})

    def test_user_id_forced_and_protected(self):
        transfer = self.env["stock.branch.transfer"].with_user(self.user_a).with_company(self.company_a).create({
            "dest_company_id": self.company_b.id,
            "user_id": self.user_b.id,
        })
        self.assertEqual(transfer.user_id, self.user_a)
        with self.assertRaises(UserError):
            transfer.with_user(self.user_a).write({"user_id": self.user_b.id})

    def test_wizard_rejects_foreign_line(self):
        other = self.make_transfer(self.user_a, qty=5.0)
        action = self.transfer.with_user(self.user_b).action_open_receive_diff()
        wizard = self.env[action["res_model"]].with_user(self.user_b).with_context(action["context"]).create({})
        wizard.line_ids.transfer_line_id = other.line_ids
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertEqual(other.line_ids.qty_received, 0.0)

    def test_tracked_product_rejected(self):
        tracked = self.env["product.product"].create({
            "name": "Producto con lote SBT", "type": "consu", "is_storable": True,
            "company_id": False, "tracking": "lot",
        })
        with self.assertRaises(UserError):
            self.make_transfer(self.user_a, product=tracked)
