# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawLimitAndCancel(CawCommon):

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.company.caw_installment_count = 1
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _draft(self, total):
        """Retiro en borrador por el total indicado."""
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": total,
            })],
        })

    def test_no_limit_control_allows_any_amount(self):
        """Con modo 'sin control' no hay chequeo de límite."""
        self.account.write({"limit_mode": "none", "credit_limit": 10.0})
        self.assertEqual(self._draft(5000.0)._caw_check_limit(), "")

    def test_warn_mode_returns_message_but_allows(self):
        """Modo advertencia: devuelve el aviso y no bloquea."""
        self.account.write({"limit_mode": "warn", "credit_limit": 100.0})
        withdrawal = self._draft(500.0)
        message = withdrawal._caw_check_limit()
        self.assertTrue(message)
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")

    def test_block_mode_raises_without_force(self):
        """Modo bloqueo: sin forzar, no se puede confirmar."""
        self.account.write({"limit_mode": "block", "credit_limit": 100.0})
        with self.assertRaises(UserError):
            self._draft(500.0).action_confirm()

    def test_block_mode_allows_manager_force(self):
        """Modo bloqueo: el Manager puede forzar y queda registro en el chatter."""
        self.account.write({"limit_mode": "block", "credit_limit": 100.0})
        withdrawal = self._draft(500.0)
        withdrawal.with_context(caw_force_limit=True).action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        bodies = " ".join(withdrawal.message_ids.mapped("body"))
        self.assertIn("límite", bodies.lower())

    def test_limit_counts_existing_balance(self):
        """El chequeo evalúa saldo actual + total del retiro contra el límite."""
        self.account.write({"limit_mode": "block", "credit_limit": 1000.0})
        self._draft(800.0).action_confirm()
        self.account.invalidate_recordset()
        with self.assertRaises(UserError):
            self._draft(300.0).action_confirm()

    def test_cancel_without_payments_reverts_everything(self):
        """Sin pagos imputados: se cancelan las cuotas y se cancela el albarán."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(200.0)
        withdrawal.action_confirm()
        picking = withdrawal.picking_id
        withdrawal.action_cancel()
        self.assertEqual(withdrawal.state, "cancel")
        self.assertFalse(withdrawal.installment_ids)
        if picking:
            self.assertEqual(picking.state, "cancel")

    def test_cancel_is_blocked_with_allocated_payments(self):
        """Con pagos imputados la cancelación se bloquea: primero hay que anular el pago."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(200.0)
        withdrawal.action_confirm()
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": 50.0,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        payment.action_post()
        with self.assertRaises(UserError):
            withdrawal.action_cancel()
        self.assertNotEqual(withdrawal.state, "cancel")

    def test_cancel_is_blocked_with_picking_done(self):
        """No se puede cancelar un retiro cuyo albarán ya fue validado (stock entregado)."""
        self.account.limit_mode = "none"
        self.company.caw_picking_type_id = self.warehouse.out_type_id
        withdrawal = self._draft(200.0)
        withdrawal.action_confirm()
        withdrawal.action_validate_picking()
        with self.assertRaises(UserError):
            withdrawal.action_cancel()
        self.assertNotEqual(withdrawal.state, "cancel")

    def _cc_user(self, login="caw_operator_test"):
        """Crea un usuario con solo el grupo Operador (sin Manager)."""
        return self.env["res.users"].create({
            "name": "Operador CC Test",
            "login": login,
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("checking_account_withdrawals.group_cc_user").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def test_action_cancel_requires_manager(self):
        """Un Operador sin el grupo Manager no puede cancelar un retiro."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(200.0)
        withdrawal.action_confirm()
        user = self._cc_user()
        with self.assertRaises(AccessError):
            withdrawal.with_user(user).action_cancel()

    def test_action_confirm_requires_manager(self):
        """El Operador carga el retiro pero no puede confirmarlo: lo decide el Manager."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(200.0)
        user = self._cc_user()
        with self.assertRaises(AccessError):
            withdrawal.with_user(user).action_confirm()
        self.assertEqual(withdrawal.state, "draft")

    def test_operator_cannot_open_confirm_wizard(self):
        """El Operador tampoco puede abrir el wizard que define el plan de cuotas."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(200.0)
        user = self._cc_user(login="caw_operator_wizard_test")
        with self.assertRaises(AccessError):
            withdrawal.with_user(user).action_open_confirm_wizard()

    def test_action_draft_requires_manager(self):
        """Un Operador sin el grupo Manager no puede reabrir un retiro cancelado."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(200.0)
        withdrawal.action_confirm()
        withdrawal.action_cancel()
        user = self._cc_user()
        with self.assertRaises(AccessError):
            withdrawal.with_user(user).action_draft()

    def test_wizard_generates_custom_plan(self):
        """El wizard genera el plan elegido en vez de los defaults de la compañía."""
        self.account.limit_mode = "none"
        withdrawal = self._draft(900.0)
        wizard = self.env["caw.confirm.wizard"].create({
            "withdrawal_id": withdrawal.id,
            "plan_mode": "fixed",
            "installment_count": 3,
            "first_days": 30,
            "period": "months",
            "cutoff_day": 0,
        })
        wizard.action_confirm()
        self.assertEqual(len(withdrawal.installment_ids), 3)
        self.assertEqual(withdrawal.state, "pending")
