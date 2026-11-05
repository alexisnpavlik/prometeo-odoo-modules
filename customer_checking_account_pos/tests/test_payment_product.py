# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CcaPosCommon


@tagged("post_install", "-at_install")
class TestPaymentProduct(CcaPosCommon):
    """Cobro de cuotas: el producto de pago crea un cca.payment imputado FIFO."""

    def setUp(self):
        super().setUp()
        self.env.user.groups_id += self.env.ref("customer_checking_account.group_cca_user")
        self.adjust_inventory([self.product_a], [10])
        self.open_new_session()
        self.payment_product = self.config.cca_payment_product_id

    def _sync(self, data, user=None):
        """Sincroniza un pedido (como el cajero por defecto) y devuelve el pos.order."""
        orders = self.env["pos.order"].with_user(user or self.pos_user)
        result = orders.sync_from_ui([data])
        return self.env["pos.order"].browse(result["pos.order"][0]["id"])

    def _give_debt(self, installments=3, amount=100.0):
        """Deja al cliente con una deuda en cuotas iguales vendiendo a cuenta corriente."""
        total = installments * amount
        data = self._cca_order_data(
            [(self.product_a, installments)], payments=[(self.pay_later_pm, total)],
            customer=self.cca_partner, cca_financing_set=True,
            cca_installment_count=installments, cca_surcharge_percent=0,
        )
        return self._sync(data).cca_withdrawal_id

    def _payment_data(self, amount, method=None, **extra):
        """Pedido del POS que cobra `amount` con el producto de pago."""
        return self._cca_order_data(
            [(self.payment_product, 1, {"price_unit": amount})],
            payments=[(method or self.bank_pm1, amount)],
            customer=self.cca_partner, **extra,
        )

    def _installments(self, withdrawal):
        """Cuotas de financiación del retiro, en orden."""
        return withdrawal.installment_ids.filtered(lambda i: not i.is_down_payment).sorted("sequence")

    def test_payment_product_allocates_fifo(self):
        """150 contra 3 cuotas de 100: paga la primera y deja residual 50 en la segunda."""
        withdrawal = self._give_debt()
        order = self._sync(self._payment_data(150))
        payment = order.cca_payment_id
        self.assertTrue(payment)
        self.assertAlmostEqual(payment.amount, 150.0)
        self.assertEqual(payment.payment_method, "other")
        self.assertEqual(payment.pos_order_id, order)
        self.assertEqual(payment.ref, order.pos_reference)
        self.assertEqual(payment.partner_id, self.cca_partner)
        first, second, third = self._installments(withdrawal)
        self.assertAlmostEqual(first.amount_residual, 0.0)
        self.assertAlmostEqual(second.amount_residual, 50.0)
        self.assertAlmostEqual(third.amount_residual, 100.0)
        self.assertIn(payment.name, order.cca_receipt_info)
        self.assertFalse(order.cca_withdrawal_id)

    def test_cash_payment_maps_to_cash(self):
        """Cobrado en efectivo, el pago queda como efectivo."""
        self._give_debt()
        order = self._sync(self._payment_data(100, method=self.cash_pm1))
        self.assertEqual(order.cca_payment_id.payment_method, "cash")

    def test_overpayment_leaves_credit(self):
        """Pagar de más que la deuda deja el excedente como saldo a favor."""
        self._give_debt(installments=1)
        order = self._sync(self._payment_data(130))
        account = order.cca_payment_id.account_id
        self.assertAlmostEqual(account.balance, 0.0)
        self.assertAlmostEqual(account.credit_balance, 30.0)

    def test_payment_and_cc_method_same_order_raises(self):
        """No se mezcla cobro de cuotas con venta a cuenta en el mismo pedido."""
        data = self._cca_order_data(
            [(self.payment_product, 1, {"price_unit": 100})],
            payments=[(self.pay_later_pm, 100)], customer=self.cca_partner,
        )
        with self.assertRaises(UserError):
            self._sync(data)

    def test_payment_product_requires_positive_amount(self):
        """Un pago de cuenta corriente en cero o negativo se rechaza."""
        for amount in (0.0, -50.0):
            data = self._cca_order_data(
                [(self.payment_product, 1, {"price_unit": amount})],
                payments=[(self.bank_pm1, amount)], customer=self.cca_partner,
            )
            with self.assertRaises(UserError), self.env.cr.savepoint():
                self._sync(data)

    def test_payment_product_requires_customer_and_vat(self):
        """Sin cliente o sin DNI no se cobra cuenta corriente."""
        data = self._cca_order_data(
            [(self.payment_product, 1, {"price_unit": 100})], payments=[(self.bank_pm1, 100)],
        )
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._sync(data)
        self.cca_partner.vat = False
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._sync(self._payment_data(100))

    def test_resync_creates_one_payment(self):
        """Sincronizar dos veces el mismo pedido no duplica el pago."""
        self._give_debt()
        data = self._payment_data(100)
        self._sync(data)
        self._sync(data)
        payments = self.env["cca.payment"].search([("partner_id", "=", self.cca_partner.id)])
        self.assertEqual(len(payments), 1)

    def test_payment_as_pos_user_without_cca_group(self):
        """El cajero sin grupo de cuenta corriente puede cobrar cuotas."""
        self.assertFalse(self.pos_user.has_group("customer_checking_account.group_cca_user"))
        self._give_debt()
        order = self._sync(self._payment_data(100), user=self.pos_user)
        self.assertTrue(order.cca_payment_id)
