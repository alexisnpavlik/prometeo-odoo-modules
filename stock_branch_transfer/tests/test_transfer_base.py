from odoo.exceptions import ValidationError

from .common import BranchTransferCommon


class TestTransferBase(BranchTransferCommon):

    def test_sequence_name(self):
        self.assertTrue(self.make_transfer(self.user_a).name.startswith("TRS/"))

    def test_dest_cannot_equal_origin(self):
        with self.assertRaises(ValidationError):
            self.make_transfer(self.user_a, dest=self.company_a)

    def test_record_rule_hides_foreign(self):
        transfer = self.make_transfer(self.user_a)
        Transfer = self.env["stock.branch.transfer"]
        self.assertNotIn(transfer, Transfer.with_user(self.user_c).search([]))
        self.assertIn(transfer, Transfer.with_user(self.user_b).search([]))
        self.assertIn(transfer, Transfer.with_user(self.manager).search([]))

    def test_internal_user_has_group(self):
        self.assertTrue(self.user_a.has_group("stock_branch_transfer.group_branch_transfer_user"))
        self.assertFalse(self.user_a.has_group("stock_branch_transfer.group_branch_transfer_manager"))

    def test_transit_location(self):
        self.assertEqual(self.transit.usage, "transit")
        self.assertFalse(self.transit.company_id)

    def test_unlink_draft_ok(self):
        transfer = self.make_transfer(self.user_a)
        transfer.with_user(self.user_a).unlink()
        self.assertFalse(transfer.exists())
