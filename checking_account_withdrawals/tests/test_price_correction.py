# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawPriceCorrection(CawCommon):
    """El Manager corrige precios después de entregar o confirmar, sin pagos de por medio."""

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.company.caw_installment_count = 1
        self.company.caw_picking_type_id = self.warehouse.out_type_id
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _draft(self, qty=2.0, price=100.0):
        """Retiro en borrador con una línea."""
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": qty,
                "price_unit": price,
            })],
        })

    def _cc_user(self, login="caw_price_operator_test"):
        """Usuario Operador: group_cc_user sin group_cc_manager."""
        return self.env["res.users"].create({
            "name": "Operador CC Precio",
            "login": login,
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("checking_account_withdrawals.group_cc_user").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def _posted_payment(self, amount):
        """Pago publicado, que imputa FIFO sobre las cuotas abiertas."""
        payment = self.env["caw.payment"].create({
            "account_id": self.account.id,
            "amount": amount,
            "date": "2026-06-01",
            "payment_method": "cash",
        })
        payment.action_post()
        return payment

    def test_manager_corrects_price_after_delivery(self):
        """Entregado: el Manager corrige el precio y el total acompaña."""
        withdrawal = self._draft(qty=2.0, price=100.0)
        withdrawal.action_deliver()
        self.assertEqual(withdrawal.state, "delivered")
        withdrawal.line_ids.write({"price_unit": 150.0})
        self.assertEqual(withdrawal.amount_total, 300.0)
        self.assertFalse(withdrawal.installment_ids)

    def test_manager_corrects_price_after_confirm_and_installments_follow(self):
        """Pendiente sin pagos: corregir el precio reajusta los montos de las cuotas."""
        withdrawal = self._draft(qty=2.0, price=100.0)
        withdrawal._caw_generate_installments(
            count=2, first_days=30, period="months", cutoff_day=0
        )
        installments = withdrawal.installment_ids.sorted("sequence")
        due_dates = installments.mapped("date_due")
        self.assertEqual(withdrawal.amount_total, 200.0)
        self.assertEqual(installments.mapped("amount"), [100.0, 100.0])

        withdrawal.line_ids.write({"price_unit": 150.0})

        self.assertEqual(withdrawal.amount_total, 300.0)
        installments = withdrawal.installment_ids.sorted("sequence")
        self.assertEqual(installments.mapped("amount"), [150.0, 150.0])
        self.assertEqual(installments.mapped("date_due"), due_dates)
        self.assertEqual(withdrawal.amount_residual, 300.0)
        self.assertEqual(self.account.balance, 300.0)

    def test_odd_total_keeps_rounding_in_last_installment(self):
        """El resto del redondeo sigue yendo a la última cuota, como en la generación."""
        withdrawal = self._draft(qty=1.0, price=100.0)
        withdrawal._caw_generate_installments(
            count=3, first_days=30, period="months", cutoff_day=0
        )
        withdrawal.line_ids.write({"price_unit": 100.01})
        amounts = withdrawal.installment_ids.sorted("sequence").mapped("amount")
        self.assertEqual(sum(amounts), 100.01)
        self.assertEqual(amounts[0], amounts[1])
        self.assertNotEqual(amounts[-1], amounts[0])

    def test_price_correction_blocked_with_posted_payment(self):
        """Con un pago imputado, la corrección se bloquea."""
        withdrawal = self._draft(qty=1.0, price=200.0)
        withdrawal._caw_generate_installments(
            count=1, first_days=30, period="months", cutoff_day=0
        )
        self._posted_payment(50.0)
        self.assertTrue(withdrawal._caw_posted_allocations())
        with self.assertRaises(UserError):
            withdrawal.line_ids.write({"price_unit": 300.0})

    def test_operator_cannot_correct_price_after_delivery(self):
        """El Operador no puede tocar precios de un retiro que salió de borrador."""
        withdrawal = self._draft()
        withdrawal.action_deliver()
        user = self._cc_user()
        with self.assertRaises(AccessError):
            withdrawal.line_ids.with_user(user).write({"price_unit": 999.0})

    def test_quantity_still_blocked_after_delivery(self):
        """La corrección es solo de precio: la cantidad sigue bloqueada."""
        withdrawal = self._draft()
        withdrawal.action_deliver()
        with self.assertRaises(UserError):
            withdrawal.line_ids.write({"quantity": 5.0})

    def test_new_line_still_blocked_after_confirm(self):
        """Tampoco se pueden agregar líneas a un retiro confirmado."""
        withdrawal = self._draft()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.write({"line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 10.0,
            })]})

    def test_price_correction_from_parent_write(self):
        """La corrección hecha desde el formulario (comando 1 en line_ids) también pasa."""
        withdrawal = self._draft(qty=1.0, price=100.0)
        withdrawal._caw_generate_installments(
            count=1, first_days=30, period="months", cutoff_day=0
        )
        withdrawal.write({"line_ids": [(1, withdrawal.line_ids.id, {"price_unit": 250.0})]})
        self.assertEqual(withdrawal.amount_total, 250.0)
        self.assertEqual(withdrawal.installment_ids.amount, 250.0)

    def test_lines_editable_flag_matches_permissions(self):
        """El flag que abre la lista en la vista sigue las mismas reglas."""
        withdrawal = self._draft()
        self.assertTrue(withdrawal.caw_lines_editable)
        withdrawal.action_deliver()
        withdrawal.invalidate_recordset()
        self.assertTrue(withdrawal.caw_lines_editable)
        user = self._cc_user(login="caw_price_operator_flag_test")
        self.assertFalse(withdrawal.with_user(user).caw_lines_editable)
