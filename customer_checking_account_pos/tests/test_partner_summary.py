# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CcaPosCommon


@tagged("post_install", "-at_install")
class TestPartnerSummary(CcaPosCommon):
    """RPC cca_pos_partner_summary: saldo del cliente para el POS."""

    def _make_debt(self, amount=100.0):
        """Retiro confirmado con cuota vencida hace 10 días, creado como superusuario."""
        self.env.user.groups_id += self.env.ref("customer_checking_account.group_cca_user")
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.cca_partner.id,
            "company_id": self.company.id,
            "date": fields.Date.today() - timedelta(days=40),
            "first_due_date": fields.Date.today() - timedelta(days=10),
            "line_ids": [Command.create({
                "product_id": self.product_a.id,
                "quantity": 1,
                "price_unit": amount,
            })],
        })
        withdrawal.action_confirm()
        return withdrawal

    def _summary(self, user=None):
        """Llama al RPC como el usuario dado (por defecto el cajero)."""
        model = self.env["res.partner"].with_user(user or self.pos_user)
        return model.cca_pos_partner_summary(self.cca_partner.id, self.company.id)

    def test_summary_without_account(self):
        """Sin cuenta devuelve ceros y no la crea."""
        result = self._summary()
        self.assertFalse(result["has_account"])
        self.assertEqual(
            (result["balance"], result["overdue"], result["credit"], result["credit_limit"]),
            (0.0, 0.0, 0.0, 0.0),
        )
        self.assertEqual(result["limit_mode"], "none")
        self.assertFalse(self.env["cca.account"].sudo().search_count([("partner_id", "=", self.cca_partner.id)]))

    def test_summary_with_debt(self):
        """Saldo y vencido reflejan una cuota vencida."""
        self._make_debt(100.0)
        result = self._summary()
        self.assertTrue(result["has_account"])
        self.assertEqual(result["balance"], 100.0)
        self.assertEqual(result["overdue"], 100.0)
        self.assertEqual(result["credit"], 0.0)

    def test_summary_as_pos_user_without_cca_group(self):
        """El cajero sin group_cca_user puede consultarlo."""
        self._make_debt(100.0)
        self.assertFalse(self.pos_user.has_group("customer_checking_account.group_cca_user"))
        self.assertEqual(self._summary(self.pos_user)["balance"], 100.0)

    def test_summary_requires_pos_group(self):
        """Un usuario interno sin grupo POS recibe AccessError."""
        user = self.env["res.users"].create({
            "name": "Interno sin POS",
            "login": "interno_sin_pos",
            "company_id": self.company.id,
            "company_ids": [Command.set(self.company.ids)],
            "groups_id": [Command.set([self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self._summary(user)

    def test_summary_rejects_foreign_company(self):
        """Una compañía fuera de las del usuario da AccessError."""
        other = self.env["res.company"].create({"name": "Otra compañía"})
        with self.assertRaises(AccessError):
            self.env["res.partner"].with_user(self.pos_user).cca_pos_partner_summary(
                self.cca_partner.id, other.id
            )
