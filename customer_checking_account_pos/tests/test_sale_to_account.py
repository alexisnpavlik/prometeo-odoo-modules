# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CcaPosCommon


@tagged("post_install", "-at_install")
class TestSaleToAccount(CcaPosCommon):
    """Venta a cuenta corriente: el sync del POS crea y confirma el retiro."""

    def setUp(self):
        super().setUp()
        # El usuario del test revisa los retiros; el cajero (pos_user) sigue sin el grupo.
        self.env.user.groups_id += self.env.ref("customer_checking_account.group_cca_user")
        self.adjust_inventory([self.product_a], [10])
        self.open_new_session()

    def _sync(self, data):
        """Sincroniza un pedido como el cajero y devuelve el pos.order."""
        result = self.env["pos.order"].with_user(self.pos_user).sync_from_ui([data])
        return self.env["pos.order"].browse(result["pos.order"][0]["id"])

    def _available(self):
        """Cantidad disponible de product_a en la compañía."""
        return self.product_a.with_company(self.company).qty_available

    def _withdrawals_of(self, order):
        """Retiros que apuntan al pedido."""
        return self.env["cca.withdrawal"].search([("pos_order_id", "=", order.id)])

    def test_full_amount_to_account(self):
        """Todo a cuenta: retiro confirmado con recargo, cuotas y sin venta ni stock doble."""
        before = self._available()
        data = self._cca_order_data(
            [(self.product_a, 2)], payments=[(self.pay_later_pm, 200)], customer=self.cca_partner,
            cca_financing_set=True, cca_installment_count=3, cca_surcharge_percent=10,
        )
        order = self._sync(data)
        withdrawal = order.cca_withdrawal_id
        self.assertTrue(withdrawal)
        self.assertTrue(withdrawal.is_confirmed)
        self.assertEqual(withdrawal.pos_order_id, order)
        self.assertEqual(withdrawal.partner_id, self.cca_partner)
        self.assertAlmostEqual(withdrawal.amount_total, 220.0)
        self.assertEqual(len(withdrawal.installment_ids.filtered(lambda i: not i.is_down_payment)), 3)
        self.assertEqual(withdrawal.down_payment, 0.0)
        self.assertFalse(withdrawal.sale_order_id)
        self.assertEqual(self._available(), before - 2)

    def test_mixed_payment_becomes_down_payment(self):
        """Lo pagado con otro medio entra como entrega; el recargo va solo sobre lo financiado."""
        data = self._cca_order_data(
            [(self.product_a, 2)],
            payments=[(self.cash_pm1, 50), (self.pay_later_pm, 150)],
            customer=self.cca_partner,
            cca_financing_set=True, cca_surcharge_percent=10,
        )
        withdrawal = self._sync(data).cca_withdrawal_id
        self.assertAlmostEqual(withdrawal.down_payment, 50.0)
        self.assertEqual(withdrawal.down_payment_method, "cash")
        self.assertAlmostEqual(withdrawal.amount_surcharge, 15.0)
        self.assertEqual(withdrawal.installment_count, 1)
        self.assertTrue(withdrawal.down_payment_id)

    def test_defaults_from_company_when_empty(self):
        """Sin financiación en el pedido se usan los valores de la compañía."""
        self.company.write({"cca_pos_installment_count": 2, "cca_pos_first_due_days": 15})
        data = self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.pay_later_pm, 100)], customer=self.cca_partner,
        )
        order = self._sync(data)
        withdrawal = order.cca_withdrawal_id
        installments = withdrawal.installment_ids.filtered(lambda i: not i.is_down_payment).sorted("sequence")
        self.assertEqual(len(installments), 2)
        local_date = fields.Date.context_today(order, timestamp=order.date_order)
        self.assertEqual(installments[0].date_due, local_date + timedelta(days=15))
        self.assertEqual(withdrawal.date, local_date)

    def test_invalid_company_defaults_are_clamped(self):
        """Defaults inválidos de la compañía no rompen la venta: 1 cuota, sin recargo."""
        self.company.write({
            "cca_pos_installment_count": 0,
            "cca_pos_surcharge_percent": -5,
            "cca_pos_first_due_days": -3,
        })
        data = self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.pay_later_pm, 100)], customer=self.cca_partner,
        )
        order = self._sync(data)
        withdrawal = order.cca_withdrawal_id
        self.assertEqual(withdrawal.installment_count, 1)
        self.assertEqual(withdrawal.surcharge_percent, 0.0)
        self.assertEqual(withdrawal.first_due_date, withdrawal.date)

    def test_discounted_line_price_matches_ticket(self):
        """Con descuento, la deuda coincide con el total del ticket."""
        data = self._cca_order_data(
            [(self.product_a, 1, {"discount": 10, "price_unit": 100.0})],
            payments=[(self.pay_later_pm, 90)], customer=self.cca_partner,
        )
        order = self._sync(data)
        self.assertAlmostEqual(order.cca_withdrawal_id.amount_untaxed, order.amount_total)

    def test_taxed_odd_quantity_matches_ticket(self):
        """IVA 21% y cantidad 3: el retiro reproduce el total del ticket sin diferencia de centavos."""
        tax = self.env["account.tax"].create({
            "name": "IVA 21 CCA",
            "amount": 21.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "company_id": self.company.id,
        })
        product = self.env["product.product"].create({
            "name": "Producto con IVA",
            "is_storable": True,
            "available_in_pos": True,
            "list_price": 99.99,
            "taxes_id": [(6, 0, tax.ids)],
        })
        data = self._cca_order_data(
            [(product, 3)], payments=[(self.pay_later_pm, 362.96)], customer=self.cca_partner,
        )
        self.assertAlmostEqual(data["amount_total"], 362.96, places=2)
        order = self._sync(data)
        withdrawal = order.cca_withdrawal_id
        self.assertEqual(
            self.currency.compare_amounts(withdrawal.amount_untaxed, order.amount_total), 0
        )
        self.assertIn("3 x", withdrawal.line_ids.name)

    def test_cc_amount_above_total_raises(self):
        """Pagar a cuenta más que el total (y dar vuelto en efectivo) se rechaza."""
        data = self._cca_order_data(
            [(self.product_a, 1)],
            payments=[(self.pay_later_pm, 150), (self.cash_pm1, -50)],
            customer=self.cca_partner,
        )
        with self.assertRaises(UserError) as error:
            self._sync(data)
        self.assertIn("no puede superar el total", str(error.exception))
        self.assertFalse(self.env["pos.order"].search([("uuid", "=", data["uuid"])]))

    def test_negative_line_with_cc_raises(self):
        """Una línea negativa en una venta a cuenta se rechaza."""
        data = self._cca_order_data(
            [(self.product_a, 2), (self.product_a, 1, {"price_unit": -50.0})],
            payments=[(self.pay_later_pm, 150)], customer=self.cca_partner,
        )
        with self.assertRaises(UserError) as error:
            self._sync(data)
        self.assertIn("líneas negativas", str(error.exception))
        self.assertFalse(self.env["pos.order"].search([("uuid", "=", data["uuid"])]))

    def test_resync_same_uuid_creates_one_withdrawal(self):
        """Reenviar el mismo pedido no duplica el retiro."""
        data = self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.pay_later_pm, 100)], customer=self.cca_partner,
        )
        order = self._sync(dict(data))
        self._sync(dict(data))
        self.assertEqual(len(self._withdrawals_of(order)), 1)
        # Llamar de nuevo al proceso tampoco duplica.
        order._cca_process()
        self.assertEqual(len(self._withdrawals_of(order)), 1)

    def test_no_partner_raises(self):
        """Pago a cuenta sin cliente: error y el pedido no queda guardado."""
        data = self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.pay_later_pm, 100)],
        )
        with self.assertRaises(UserError) as error:  # el de Odoo abre un savepoint: simula el rollback
            self._sync(data)
        self.assertIn("Elegí un cliente", str(error.exception))
        self.assertFalse(self.env["pos.order"].search([("uuid", "=", data["uuid"])]))

    def test_partner_without_vat_raises(self):
        """Cliente sin DNI: error y el pedido no queda guardado."""
        partner = self.env["res.partner"].create({"name": "Sin DNI"})
        data = self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.pay_later_pm, 100)], customer=partner,
        )
        with self.assertRaises(UserError) as error:  # el de Odoo abre un savepoint: simula el rollback
            self._sync(data)
        self.assertIn("DNI de Sin DNI", str(error.exception))
        self.assertFalse(self.env["pos.order"].search([("uuid", "=", data["uuid"])]))

    def test_block_limit_raises(self):
        """Límite en modo bloqueo: el error del base llega al POS."""
        account = self.env["cca.account"].sudo()._get_or_create(self.cca_partner, self.company)
        account.write({"credit_limit": 100, "limit_mode": "block"})
        data = self._cca_order_data(
            [(self.product_a, 2)], payments=[(self.pay_later_pm, 200)], customer=self.cca_partner,
        )
        with self.assertRaises(UserError) as error:  # el de Odoo abre un savepoint: simula el rollback
            self._sync(data)
        self.assertIn("límite", str(error.exception))
        self.assertFalse(self.env["pos.order"].search([("uuid", "=", data["uuid"])]))

    def test_receipt_info_filled(self):
        """El ticket recibe el número de retiro y las cuotas."""
        data = self._cca_order_data(
            [(self.product_a, 2)], payments=[(self.pay_later_pm, 200)], customer=self.cca_partner,
            cca_financing_set=True, cca_installment_count=2,
        )
        order = self._sync(data)
        self.assertIn(order.cca_withdrawal_id.name, order.cca_receipt_info)
        self.assertIn("2 cuota(s)", order.cca_receipt_info)

    def test_cash_order_without_cc_untouched(self):
        """Un pedido común no genera nada de cuenta corriente."""
        data = self._cca_order_data(
            [(self.product_a, 1)], payments=[(self.cash_pm1, 100)], customer=self.cca_partner,
        )
        order = self._sync(data)
        self.assertFalse(order.cca_withdrawal_id)
        self.assertFalse(self._withdrawals_of(order))
