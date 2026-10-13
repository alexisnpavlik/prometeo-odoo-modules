# -*- coding: utf-8 -*-
from datetime import date

from .common import CcaCommon


class TestPartner(CcaCommon):

    def test_search_partner_by_dni(self):
        """El selector de cliente encuentra al contacto por DNI."""
        found = self.env["res.partner"].name_search("30111222")
        self.assertIn(self.partner.id, [pid for pid, _name in found])

    def test_display_name_shows_dni_with_context(self):
        """Con show_vat el nombre muestra el DNI."""
        name = self.partner.with_context(show_vat=True).display_name
        self.assertIn("30111222", name)

    def test_partner_balance_and_count(self):
        """El contacto muestra saldo y cantidad de retiros."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "line_ids": [(0, 0, {"product_id": self.service.id, "quantity": 2})],
        })
        withdrawal.action_confirm()
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.cca_balance, 100.0)
        self.assertEqual(self.partner.cca_withdrawal_count, 1)

    def test_views_load(self):
        """Las vistas principales se renderizan sin error."""
        for model in ("cca.withdrawal", "cca.payment", "cca.account", "cca.installment"):
            self.env[model].get_views([(False, "list"), (False, "form")])
