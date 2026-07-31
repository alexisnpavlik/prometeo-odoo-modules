# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviRecovery(CviCommon):
    """E7: mora (HU-23, HU-24) y recupero del mueble (HU-25, HU-26)."""

    def setUp(self):
        super().setUp()
        # Venta vieja y sin tolerancia: las cuotas quedan vencidas de verdad.
        self.company.cvi_overdue_days = 0
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    # --- mora (HU-23, HU-24) ---

    def test_overdue_amount_sums_the_unpaid_due_installments(self):
        self.assertGreater(self.card.amount_overdue, 0.0)
        self.assertEqual(
            self.card.amount_overdue,
            sum(self.card.installment_ids.filtered(
                lambda i: i.state == "overdue" and not i.is_commission
            ).mapped("amount_residual")),
        )

    def test_days_overdue_counts_from_the_oldest_unpaid(self):
        """La antigüedad es la de la cuota más vieja, que es el criterio de HU-24."""
        overdue = self.card.installment_ids.filtered(
            lambda i: i.state == "overdue" and not i.is_commission
        )
        oldest = min(overdue.mapped("date_due"))
        from odoo import fields as odoo_fields
        expected = (odoo_fields.Date.context_today(self.card) - oldest).days
        self.assertEqual(self.card.days_overdue, expected)

    def test_commission_is_not_counted_as_client_debt(self):
        """La primera cuota es del vendedor: no es deuda del cliente en mora."""
        commission = self.card.installment_ids.filtered("is_commission")
        self.assertTrue(commission)
        self.assertNotIn(commission, self.card.installment_ids.filtered(
            lambda i: i.state == "overdue" and not i.is_commission
        ))

    def test_a_card_up_to_date_has_no_overdue_days(self):
        current = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2099-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        current.action_confirm()
        self.assertEqual(current.days_overdue, 0)
        self.assertEqual(current.amount_overdue, 0.0)

    # --- marcar para retiro (HU-25) ---

    def test_marking_requires_a_reason(self):
        with self.assertRaises(UserError):
            self.card.action_mark_to_recover()

    def test_marking_records_who_and_when(self):
        self.card.to_recover_reason = "Cuatro meses sin pagar, no atiende."
        self.card.action_mark_to_recover()
        self.assertTrue(self.card.to_recover)
        self.assertEqual(self.card.to_recover_user_id, self.env.user)
        self.assertTrue(self.card.to_recover_date)

    def test_marking_does_not_stop_collection(self):
        """Es una marca, no un estado: si el cliente paga, la tarjeta se salva."""
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.assertEqual(self.card.state, "active")

    def test_a_marked_card_can_be_unmarked(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_unmark_to_recover()
        self.assertFalse(self.card.to_recover)

    def test_cannot_mark_a_card_that_is_not_in_collection(self):
        draft = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        draft.to_recover_reason = "Sin pagar."
        with self.assertRaises(UserError):
            draft.action_mark_to_recover()

    def test_cannot_mark_twice(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        with self.assertRaises(UserError):
            self.card.action_mark_to_recover()

    # --- registrar el retiro (HU-26) ---

    def test_recovery_needs_the_card_marked_first(self):
        with self.assertRaises(UserError):
            self.card.action_register_recovery()

    def test_recovery_closes_the_card(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        self.assertEqual(self.card.state, "recovered")

    def test_recovery_records_what_had_been_paid(self):
        """Cuánto pagó el cliente hasta el retiro es el dato que después se discute."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 5000.0, "date": "2020-03-10",
        })
        payment.action_post()
        paid_before = self.card.amount_paid
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        self.assertEqual(self.card.amount_paid_at_recovery, paid_before)

    def test_recovered_unit_goes_to_the_recovered_location(self):
        """No vuelve al stock vendible: un mueble usado no es uno nuevo."""
        location = self.env.ref(
            "collections_from_vendors_installments.stock_location_recovered"
        )
        before = self.env["stock.quant"]._get_available_quantity(
            self.product, location
        )
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        after = self.env["stock.quant"]._get_available_quantity(self.product, location)
        self.assertEqual(after, before + self.card.quantity)

    def test_recovery_leaves_a_validated_picking(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        self.assertTrue(self.card.recovery_picking_id)
        self.assertEqual(self.card.recovery_picking_id.state, "done")

    def test_cannot_recover_twice(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        with self.assertRaises(UserError):
            self.card.action_register_recovery()

    def test_recovered_card_is_out_of_the_collection_agenda(self):
        """Una tarjeta retirada deja de generar cobranza (HU-26).

        La agenda filtra card_state == 'active'; al pasar a 'recovered' sale sola.
        """
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        agenda = self.env["cvi.installment"].search([
            ("card_state", "=", "active"),
            ("is_commission", "=", False),
            ("card_id", "=", self.card.id),
        ])
        self.assertFalse(agenda)
