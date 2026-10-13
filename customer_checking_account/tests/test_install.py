# -*- coding: utf-8 -*-
from .common import CcaCommon


class TestInstall(CcaCommon):

    def test_group_and_sequences_exist(self):
        """El grupo único y las dos secuencias quedan instalados."""
        self.assertTrue(self.env.ref("customer_checking_account.group_cca_user"))
        seq = self.env["ir.sequence"]
        self.assertTrue(seq.search([("code", "=", "cca.withdrawal")]))
        self.assertTrue(seq.search([("code", "=", "cca.payment")]))
