# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawAccount(CawCommon):

    def test_enabling_partner_creates_account(self):
        """Marcar caw_enabled crea automáticamente la cuenta de la compañía activa."""
        self.assertFalse(self.partner.caw_account_ids)
        self.partner.caw_enabled = True
        account = self.partner.caw_account_ids
        self.assertEqual(len(account), 1)
        self.assertEqual(account.partner_id, self.partner)
        self.assertEqual(account.company_id, self.company)
        self.assertEqual(account.limit_mode, "none")

    def test_account_is_unique_per_partner_and_company(self):
        """No se pueden crear dos cuentas para el mismo partner en la misma compañía."""
        self.partner.caw_enabled = True
        with self.assertRaises(Exception):
            self.env["caw.account"].create({
                "partner_id": self.partner.id,
                "company_id": self.company.id,
            })
            self.env.flush_all()

    def test_get_or_create_is_idempotent(self):
        """_get_or_create devuelve la cuenta existente en vez de duplicarla."""
        first = self.env["caw.account"]._get_or_create(self.partner, self.company)
        second = self.env["caw.account"]._get_or_create(self.partner, self.company)
        self.assertEqual(first, second)
