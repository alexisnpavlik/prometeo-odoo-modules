# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCardState(CviCommon):

    def setUp(self):
        super().setUp()
        # date_sale fija en el pasado; sin tolerancia las cuotas de cobranza
        # quedarían "overdue" en vez de "pending", rompiendo asserts que no
        # tienen que ver con mora. test_overdue_count_reflects_late_installments
        # pisa este valor a 0 explícitamente donde sí necesita mora real.
        self.company.cvi_overdue_days = 3650  # ~10 años
        self.card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        # La entrega ya no se cobra sola al confirmar: estos tests miden saldos que
        # la incluyen, así que la registran explícitamente.
        self.card.action_charge_first_installment()
        self.card.action_accept()

    def _pay(self, amount):
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": amount, "date": "2026-02-10",
        })
        payment.action_post()
        return payment

    def test_amount_paid_includes_commission(self):
        """Tras confirmar, lo cobrado es la comisión de la primera cuota."""
        self.assertEqual(self.card.amount_paid, 10000.0)

    def test_amount_residual_is_what_is_left(self):
        """El residual de la tarjeta es el total menos lo cobrado."""
        self.assertEqual(self.card.amount_residual, 20000.0)

    def test_counts_after_confirm(self):
        """Con la comisión cobrada: 1 cuota pagada, 2 pendientes (HU-16)."""
        self.assertEqual(self.card.paid_installment_count, 1)
        self.assertEqual(self.card.pending_installment_count, 2)

    def test_next_due_date_is_next_unpaid_collection_installment(self):
        """La próxima fecha de cobro es la de la cuota 2 (la 1 ya está cobrada)."""
        self.assertEqual(str(self.card.next_due_date), "2026-02-10")

    def test_paying_advances_the_next_due_date(self):
        """Al cobrar la cuota 2, la próxima fecha pasa a la de la cuota 3."""
        self._pay(10000.0)
        self.assertEqual(str(self.card.next_due_date), "2026-03-10")

    def test_partial_payment_updates_balance(self):
        """Un cobro parcial actualiza el saldo de la tarjeta al instante (HU-15)."""
        self._pay(4000.0)
        self.assertEqual(self.card.amount_paid, 14000.0)
        self.assertEqual(self.card.amount_residual, 16000.0)

    def test_card_closes_when_fully_paid(self):
        """Al cubrirse el total, la tarjeta pasa sola a Finalizada (HU-17)."""
        self._pay(20000.0)
        self.assertEqual(self.card.amount_residual, 0.0)
        self.assertEqual(self.card.state, "done")

    def test_card_does_not_close_while_residual_remains(self):
        """Mientras quede residual, la tarjeta sigue en cobranza."""
        self._pay(19999.0)
        self.assertEqual(self.card.state, "active")

    def test_cancelling_a_payment_reopens_a_closed_card(self):
        """Anular un cobro sobre una tarjeta saldada la devuelve a cobranza."""
        payment = self._pay(20000.0)
        self.assertEqual(self.card.state, "done")
        payment.action_cancel()
        self.assertEqual(self.card.state, "active")
        self.assertEqual(self.card.amount_residual, 20000.0)

    def test_overdue_count_reflects_late_installments(self):
        """Las cuotas impagas ya vencidas se cuentan como vencidas (HU-16)."""
        self.company.cvi_overdue_days = 0
        old = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        old.action_confirm()
        old.action_charge_first_installment()
        self.assertEqual(old.overdue_installment_count, 2)
