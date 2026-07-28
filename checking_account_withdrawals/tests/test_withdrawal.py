# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawWithdrawal(CawCommon):

    def _new_withdrawal(self, lines=None):
        """Crea un retiro en borrador con las líneas indicadas."""
        self.partner.caw_enabled = True
        lines = lines or [(2.0, 150.0), (1.0, 300.0)]
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "line_ids": [
                (0, 0, {
                    "product_id": self.product.id,
                    "quantity": qty,
                    "price_unit": price,
                })
                for qty, price in lines
            ],
        })

    def test_amount_total_sums_lines(self):
        """El total del retiro es la suma de los subtotales de sus líneas."""
        withdrawal = self._new_withdrawal()
        self.assertEqual(withdrawal.line_ids[0].price_subtotal, 300.0)
        self.assertEqual(withdrawal.line_ids[1].price_subtotal, 300.0)
        self.assertEqual(withdrawal.amount_total, 600.0)

    def test_account_is_assigned_from_partner(self):
        """Al crear el retiro se resuelve la cuenta corriente del partner."""
        withdrawal = self._new_withdrawal()
        self.assertTrue(withdrawal.account_id)
        self.assertEqual(withdrawal.account_id.partner_id, self.partner)
        self.assertEqual(withdrawal.account_id.company_id, withdrawal.company_id)

    def test_name_comes_from_sequence(self):
        """El retiro toma su número de la secuencia propia del módulo."""
        withdrawal = self._new_withdrawal()
        self.assertNotEqual(withdrawal.name, "/")
        self.assertTrue(withdrawal.name.startswith("CC/"))

    def test_starts_in_draft(self):
        """Un retiro nace en borrador."""
        self.assertEqual(self._new_withdrawal().state, "draft")

    def test_disabled_partner_is_rejected(self):
        """No se puede crear un retiro para un contacto sin cuenta corriente habilitada."""
        from odoo.exceptions import UserError
        other = self.env["res.partner"].create({"name": "No habilitado"})
        with self.assertRaises(UserError):
            self.env["caw.withdrawal"].create({"partner_id": other.id})

    def test_line_write_blocked_after_confirm(self):
        """Una vez confirmado el retiro, no se puede editar una línea directamente."""
        from odoo.exceptions import UserError
        withdrawal = self._new_withdrawal()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.line_ids.write({"price_unit": 999.0})

    def test_line_unlink_blocked_after_confirm(self):
        """Una vez confirmado el retiro, no se puede borrar una línea directamente."""
        from odoo.exceptions import UserError
        withdrawal = self._new_withdrawal()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.line_ids[0].unlink()
