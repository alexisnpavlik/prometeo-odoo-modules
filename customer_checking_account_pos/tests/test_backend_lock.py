# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CcaPosCommon


@tagged("post_install", "-at_install")
class TestBackendLock(CcaPosCommon):
    """Retiros nacidos en el POS: sin stock propio y bloqueados en el backend."""

    def setUp(self):
        super().setUp()
        self.env.user.groups_id += self.env.ref("customer_checking_account.group_cca_user")
        self.adjust_inventory([self.product_a], [10])
        self.open_new_session()

    def _available(self):
        """Cantidad disponible de product_a en la compañía."""
        return self.product_a.with_company(self.company).qty_available

    def _make_withdrawal(self):
        """Pedido POS pagado en efectivo + retiro confirmado apuntando a él."""
        data = self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.cash_pm1, 100)], customer=self.cca_partner
        )
        result = self.env["pos.order"].sync_from_ui([data])
        order = self.env["pos.order"].browse(result["pos.order"][0]["id"])
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.cca_partner.id,
            "company_id": self.company.id,
            "pos_order_id": order.id,
            "line_ids": [Command.create({
                "product_id": self.product_a.id,
                "quantity": 1,
                "price_unit": 100.0,
            })],
        })
        withdrawal.action_confirm()
        return withdrawal, order

    def test_confirm_pos_withdrawal_creates_no_sale_order(self):
        """Confirmar no crea venta y el stock baja solo por el pedido POS."""
        before = self._available()
        withdrawal, order = self._make_withdrawal()
        self.assertFalse(withdrawal.sale_order_id)
        self.assertEqual(withdrawal.picking_id, order.picking_ids[:1])
        self.assertEqual(self._available(), before - 1)

    def test_cancel_pos_withdrawal_from_backend_blocked(self):
        """Cancelar desde el backend está bloqueado."""
        withdrawal, _order = self._make_withdrawal()
        with self.assertRaises(UserError):
            withdrawal.action_cancel()

    def test_cancel_with_refund_context_does_not_return_stock(self):
        """Con el contexto del reembolso se cancela sin devolver stock."""
        withdrawal, _order = self._make_withdrawal()
        stock = self._available()
        withdrawal.with_context(cca_pos_refund=True).action_cancel()
        self.assertEqual(withdrawal.state, "cancel")
        self.assertFalse(withdrawal.return_picking_id)
        self.assertEqual(self._available(), stock)

    def test_edit_pos_withdrawal_only_due_dates(self):
        """Editar solo habilita vencimientos: no vuelve a borrador ni toca el albarán."""
        withdrawal, _order = self._make_withdrawal()
        picking = withdrawal.picking_id
        withdrawal.action_edit()
        self.assertNotEqual(withdrawal.state, "draft")
        self.assertTrue(withdrawal.is_confirmed)
        self.assertTrue(withdrawal.edit_due_dates)
        self.assertEqual(withdrawal.picking_id, picking)

    def test_draft_pos_withdrawal_blocked(self):
        """Volver a borrador está bloqueado."""
        withdrawal, _order = self._make_withdrawal()
        withdrawal.with_context(cca_pos_refund=True).action_cancel()
        with self.assertRaises(UserError):
            withdrawal.action_draft()

    def test_write_lines_of_confirmed_pos_withdrawal_blocked(self):
        """No se cambian líneas ni cliente de un retiro POS confirmado."""
        withdrawal, _order = self._make_withdrawal()
        with self.assertRaises(UserError):
            withdrawal.write({"line_ids": [Command.clear()]})
        with self.assertRaises(UserError):
            withdrawal.write({"partner_id": self.env.user.partner_id.id})
