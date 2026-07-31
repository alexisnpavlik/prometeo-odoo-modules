# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCardConfirm(CviCommon):

    def _card(self, **kwargs):
        """Tarjeta en borrador con valores mínimos, sobreescribibles."""
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_12.id,
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        return self.env["cvi.card"].create(vals)

    def test_confirm_moves_card_to_sold(self):
        """Confirmar una venta sin cobrador la deja Vendida."""
        card = self._card()
        card.action_confirm()
        self.assertEqual(card.state, "sold")

    def test_confirm_generates_the_schedule(self):
        """Confirmar genera el calendario completo de cuotas del plan (HU-06)."""
        card = self._card(plan_id=self.plan_12.id)
        card.action_confirm()
        self.assertEqual(len(card.installment_ids), 12)

    def test_confirm_charges_the_first_installment(self):
        """La primera cuota queda cobrada por el vendedor al confirmar (HU-09, RN-01)."""
        card = self._card()
        card.action_confirm()
        first = card.installment_ids.filtered(lambda i: i.sequence == 1)
        self.assertEqual(first.state, "paid")

    def test_commission_payment_is_flagged_and_attributed_to_vendor(self):
        """El cobro de la comisión se identifica por separado y queda a nombre del vendedor."""
        card = self._card()
        card.action_confirm()
        commission = card.payment_ids.filtered("is_commission")
        self.assertEqual(len(commission), 1)
        self.assertEqual(commission.amount, card.installment_amount)
        self.assertEqual(commission.user_id, self.vendor_user)
        self.assertEqual(commission.state, "posted")

    def test_second_installment_stays_pending_after_confirm(self):
        """Confirmar no toca las cuotas de cobranza: siguen pendientes para el cobrador."""
        card = self._card()
        card.action_confirm()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(second.state, "pending")

    def test_confirm_with_collector_goes_straight_to_routed(self):
        """Si el vendedor eligió cobrador al cargar la venta, la tarjeta queda enrutada (HU-10)."""
        card = self._card(collector_id=self.collector_user.id)
        card.action_confirm()
        self.assertEqual(card.state, "routed")

    def test_confirming_twice_is_rejected(self):
        """Una tarjeta ya confirmada no se vuelve a confirmar."""
        card = self._card()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.action_confirm()

    def test_plan_is_frozen_after_confirm(self):
        """Tras confirmar no se puede cambiar el plan, que es lo que fija el precio (RN-05)."""
        card = self._card()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.plan_id = self.plan_3.id

    def test_price_is_frozen_after_confirm(self):
        """Tras confirmar no se puede cambiar el importe de cuota (RN-05)."""
        card = self._card()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.installment_amount = 20000.0

    def test_installment_count_is_frozen_after_confirm(self):
        """Tras confirmar no se puede cambiar la cantidad de cuotas (RN-05)."""
        card = self._card()
        card.action_confirm()
        with self.assertRaises(UserError):
            card.installment_count = 6

    def test_product_is_frozen_after_confirm(self):
        """Tras confirmar no se puede cambiar el modelo de mueble vendido (RN-05)."""
        card = self._card()
        card.action_confirm()
        other = self.env["product.product"].create({
            "name": "Mesa de luz", "type": "consu", "is_storable": True,
        })
        with self.assertRaises(UserError):
            card.product_id = other.id

    def test_collector_can_still_be_changed_after_confirm(self):
        """El cobrador sí se puede cambiar tras confirmar: es el enrutamiento (HU-11, HU-30)."""
        card = self._card()
        card.action_confirm()
        card.collector_id = self.collector_user.id
        self.assertEqual(card.collector_id, self.collector_user)

    def test_plan_can_be_changed_while_draft(self):
        """En borrador el vendedor todavía puede cambiar de plan y reprecia la venta."""
        card = self._card()
        card.plan_id = self.plan_3.id
        self.assertEqual(card.installment_count, 3)
        self.assertEqual(card.amount_total, 30000.0)

    def test_cancel_from_draft(self):
        """Una tarjeta en borrador se puede anular."""
        card = self._card()
        card.action_cancel()
        self.assertEqual(card.state, "cancel")

    def test_cancel_from_sold(self):
        """Una tarjeta vendida sin cobrar cuotas de cobranza se puede anular."""
        card = self._card()
        card.action_confirm()
        card.action_cancel()
        self.assertEqual(card.state, "cancel")
