# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import CcaCommon


class TestAccount(CcaCommon):

    def test_get_or_create_is_idempotent(self):
        """La segunda llamada devuelve la misma cuenta."""
        account_model = self.env["cca.account"]
        first = account_model._get_or_create(self.partner, self.company)
        second = account_model._get_or_create(self.partner, self.company)
        self.assertEqual(first, second)

    def test_get_or_create_reactivates_archived(self):
        """Una cuenta archivada se reactiva en lugar de duplicarse."""
        account = self.env["cca.account"]._get_or_create(self.partner, self.company)
        account.active = False
        again = self.env["cca.account"]._get_or_create(self.partner, self.company)
        self.assertEqual(account, again)
        self.assertTrue(again.active)

    def test_new_account_takes_company_defaults(self):
        """La cuenta nueva toma límite y modo por defecto de la compañía."""
        self.company.cca_default_credit_limit = 5000.0
        self.company.cca_default_limit_mode = "warn"
        account = self.env["cca.account"]._get_or_create(self.partner, self.company)
        self.assertEqual(account.credit_limit, 5000.0)
        self.assertEqual(account.limit_mode, "warn")

    def test_negative_credit_limit_rejected(self):
        """El límite de crédito no puede ser negativo."""
        account = self.env["cca.account"]._get_or_create(self.partner, self.company)
        with self.assertRaises(ValidationError):
            account.credit_limit = -1
