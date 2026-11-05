# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CcaPosCommon


@tagged("post_install", "-at_install")
class TestRefund(CcaPosCommon):
    """Reembolsos en el POS: anulan el retiro o el pago de cuenta corriente del pedido original."""

    def setUp(self):
        super().setUp()
        self.env.user.groups_id += self.env.ref("customer_checking_account.group_cca_user")
        self.adjust_inventory([self.product_a], [10])
        self.open_new_session()
        self.payment_product = self.config.cca_payment_product_id

    def _sync(self, data):
        """Sincroniza un pedido como el cajero y devuelve el pos.order."""
        result = self.env["pos.order"].with_user(self.pos_user).sync_from_ui([data])
        return self.env["pos.order"].browse(result["pos.order"][0]["id"])

    def _available(self):
        """Cantidad disponible de product_a en la compañía."""
        return self.product_a.with_company(self.company).qty_available

    def _sale(self, qty, payments):
        """Venta de product_a a cuenta corriente con la financiación indicada en el pedido."""
        return self._sync(self._cca_order_data(
            [(self.product_a, qty)], payments=payments, customer=self.cca_partner,
            cca_financing_set=True, cca_installment_count=2, cca_surcharge_percent=0,
        ))

    def _refund_data(self, original, payments, qty=None):
        """Reembolso de las líneas del pedido original (cantidad completa salvo `qty`)."""
        lines = [
            (line.product_id, -(qty if qty is not None else line.qty), {"refunded_orderline_id": line.id})
            for line in original.lines
        ]
        return self._cca_order_data(lines, payments=payments, customer=self.cca_partner)

    def _assert_not_saved(self, data):
        """El pedido rechazado no quedó guardado."""
        self.assertFalse(self.env["pos.order"].search([("uuid", "=", data["uuid"])]))

    def test_full_refund_cancels_withdrawal(self):
        """Reembolso total con el método CC: retiro cancelado, stock devuelto una sola vez."""
        before = self._available()
        original = self._sale(2, [(self.pay_later_pm, 200)])
        withdrawal = original.cca_withdrawal_id
        self.assertEqual(self._available(), before - 2)
        refund = self._sync(self._refund_data(original, [(self.pay_later_pm, -200)]))
        self.assertEqual(withdrawal.state, "cancel")
        self.assertEqual(self._available(), before)
        self.assertFalse(refund.cca_withdrawal_id)
        self.assertFalse(refund.cca_payment_id)
        self.assertEqual(
            self.env["cca.withdrawal"].search_count([("partner_id", "=", self.cca_partner.id)]), 1
        )

    def test_refund_resync_is_idempotent(self):
        """Reprocesar o reenviar el reembolso no falla ni crea nada."""
        original = self._sale(1, [(self.pay_later_pm, 100)])
        withdrawal = original.cca_withdrawal_id
        data = self._refund_data(original, [(self.pay_later_pm, -100)])
        refund = self._sync(data)
        self.assertEqual(withdrawal.state, "cancel")
        refund._cca_process()
        self._sync(self._refund_data(original, [(self.pay_later_pm, -100)]) | {"uuid": data["uuid"]})
        self.assertEqual(withdrawal.state, "cancel")
        self.assertEqual(self.env["pos.order"].search_count([("uuid", "=", data["uuid"])]), 1)
        self.assertEqual(
            self.env["cca.withdrawal"].search_count([("partner_id", "=", self.cca_partner.id)]), 1
        )

    def test_refund_with_wrong_method_raises(self):
        """Reembolsar en efectivo lo que se financió: error y el retiro sigue confirmado."""
        original = self._sale(2, [(self.pay_later_pm, 200)])
        withdrawal = original.cca_withdrawal_id
        data = self._refund_data(original, [(self.cash_pm1, -200)])
        with self.assertRaises(UserError) as error:
            self._sync(data)
        self.assertIn("mismos medios", str(error.exception))
        self._assert_not_saved(data)
        self.assertEqual(withdrawal.state, "pending")

    def test_mixed_refund_replicates_methods(self):
        """Venta 50 efectivo + 150 CC: el reembolso replica los medios y anula la entrega."""
        original = self._sale(2, [(self.cash_pm1, 50), (self.pay_later_pm, 150)])
        withdrawal = original.cca_withdrawal_id
        down_payment = withdrawal.down_payment_id
        self.assertTrue(down_payment)
        self._sync(self._refund_data(original, [(self.cash_pm1, -50), (self.pay_later_pm, -150)]))
        self.assertEqual(withdrawal.state, "cancel")
        self.assertEqual(down_payment.state, "cancel")
        self.assertFalse(withdrawal.down_payment_id)

    def test_refund_with_change_on_original(self):
        """El vuelto del pedido original se descuenta: se reembolsa lo que realmente quedó."""
        original = self._sync(self._cca_order_data(
            [(self.product_a, 2)], payments=[(self.cash_pm1, 100), (self.pay_later_pm, 150)],
            customer=self.cca_partner, amount_return=50,
        ))
        self.assertTrue(original.payment_ids.filtered("is_change"))
        withdrawal = original.cca_withdrawal_id
        self.assertAlmostEqual(withdrawal.down_payment, 50.0)
        self._sync(self._refund_data(original, [(self.cash_pm1, -50), (self.pay_later_pm, -150)]))
        self.assertEqual(withdrawal.state, "cancel")

    def test_partial_refund_raises(self):
        """Reembolsar 1 de 2 unidades de una venta a cuenta: error."""
        original = self._sale(2, [(self.pay_later_pm, 200)])
        withdrawal = original.cca_withdrawal_id
        data = self._refund_data(original, [(self.pay_later_pm, -100)], qty=1)
        with self.assertRaises(UserError) as error:
            self._sync(data)
        self.assertIn("Reembolso parcial", str(error.exception))
        self._assert_not_saved(data)
        self.assertEqual(withdrawal.state, "pending")

    def test_refund_with_allocated_payments_raises(self):
        """Con un pago imputado al retiro, el reembolso se rechaza y el retiro queda intacto."""
        original = self._sale(2, [(self.pay_later_pm, 200)])
        withdrawal = original.cca_withdrawal_id
        self.env["cca.payment"].create({
            "partner_id": self.cca_partner.id,
            "company_id": self.company.id,
            "date": fields.Date.today(),
            "amount": 50,
            "payment_method": "cash",
        })
        self.assertEqual(withdrawal.state, "partial")
        data = self._refund_data(original, [(self.pay_later_pm, -200)])
        with self.assertRaises(UserError) as error:
            self._sync(data)
        self.assertIn("pagos imputados", str(error.exception))
        self._assert_not_saved(data)
        self.assertEqual(withdrawal.state, "partial")

    def test_refund_payment_product_cancels_payment(self):
        """Reembolsar un cobro de 150 anula el pago y borra sus imputaciones."""
        withdrawal = self._sale(3, [(self.pay_later_pm, 300)]).cca_withdrawal_id
        original = self._sync(self._cca_order_data(
            [(self.payment_product, 1, {"price_unit": 150})],
            payments=[(self.bank_pm1, 150)], customer=self.cca_partner,
        ))
        payment = original.cca_payment_id
        self.assertTrue(payment.allocation_ids)
        refund_data = self._cca_order_data(
            [(self.payment_product, -1, {
                "price_unit": 150, "refunded_orderline_id": original.lines.id,
            })],
            payments=[(self.bank_pm1, -150)], customer=self.cca_partner,
        )
        refund = self._sync(refund_data)
        self.assertEqual(payment.state, "cancel")
        self.assertFalse(payment.allocation_ids)
        self.assertFalse(refund.cca_payment_id)
        self.assertFalse(refund.cca_withdrawal_id)
        self.assertEqual(withdrawal.state, "pending")
        refund._cca_process()
        self.assertEqual(payment.state, "cancel")

    def test_refund_non_cc_sale_with_cc_method_raises(self):
        """Reembolsar una venta en efectivo con el método CC: error y nada guardado."""
        original = self._sync(self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.cash_pm1, 100)], customer=self.cca_partner,
        ))
        self.assertFalse(original.cca_withdrawal_id)
        data = self._refund_data(original, [(self.pay_later_pm, -100)])
        with self.assertRaises(UserError) as error:
            self._sync(data)
        self.assertIn("no se vendió a cuenta corriente", str(error.exception))
        self._assert_not_saved(data)

    def test_exchange_with_cc_raises(self):
        """Cambio (reembolso + producto nuevo) con cuenta corriente: error, el retiro sigue vivo."""
        original = self._sale(2, [(self.pay_later_pm, 200)])
        withdrawal = original.cca_withdrawal_id
        line = original.lines
        data = self._cca_order_data(
            [(self.product_a, -2, {"refunded_orderline_id": line.id}), (self.product_a, 3)],
            payments=[(self.pay_later_pm, 100)], customer=self.cca_partner,
        )
        with self.assertRaises(UserError) as error:
            self._sync(data)
        self.assertIn("productos nuevos", str(error.exception))
        self._assert_not_saved(data)
        self.assertEqual(withdrawal.state, "pending")

    def test_exchange_on_cash_sale_paid_with_cc_raises(self):
        """Cambio sobre una venta en efectivo pagando la diferencia a cuenta: error."""
        original = self._sync(self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.cash_pm1, 100)], customer=self.cca_partner,
        ))
        data = self._cca_order_data(
            [(self.product_a, -1, {"refunded_orderline_id": original.lines.id}), (self.product_a, 2)],
            payments=[(self.pay_later_pm, 100)], customer=self.cca_partner,
        )
        with self.assertRaises(UserError):
            self._sync(data)
        self._assert_not_saved(data)

    def test_refund_with_positive_amounts_rejected(self):
        """Original + reembolso debe dar cero por medio: montos positivos no pasan."""
        original = self._sale(2, [(self.pay_later_pm, 200)])
        draft = self._sync(self._refund_data(original, [(self.pay_later_pm, 200)]) | {"state": "draft"})
        self.assertEqual(draft.state, "draft")
        with self.assertRaises(UserError) as error:
            draft._cca_check_refund_payments(original)
        self.assertIn("mismos medios", str(error.exception))
        self.assertEqual(original.cca_withdrawal_id.state, "pending")
