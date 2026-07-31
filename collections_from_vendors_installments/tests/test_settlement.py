# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSettlement(CviCommon):

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 3650
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_12.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    def _pay(self, amount, date="2026-02-10", user=None, **kwargs):
        vals = {
            "card_id": self.card.id,
            "amount": amount,
            "date": date,
            "user_id": (user or self.collector_user).id,
        }
        vals.update(kwargs)
        payment = self.env["cvi.payment"].create(vals)
        payment.action_post()
        return payment

    def _settlement(self, date_to="2026-02-28", frequency="monthly", collector=None):
        return self.env["cvi.settlement"].create({
            "collector_id": (collector or self.collector_user).id,
            "date_to": date_to,
            "frequency": frequency,
        })

    # --- período (HU-18) ---

    def test_daily_period_starts_and_ends_the_same_day(self):
        self.assertEqual(str(self._settlement("2026-02-10", "daily").date_from), "2026-02-10")

    def test_weekly_period_covers_seven_days(self):
        self.assertEqual(str(self._settlement("2026-02-10", "weekly").date_from), "2026-02-04")

    def test_monthly_period_starts_on_the_first(self):
        self.assertEqual(str(self._settlement("2026-02-28", "monthly").date_from), "2026-02-01")

    def test_settlement_gets_a_sequence_reference(self):
        self.assertTrue(self._settlement().name.startswith("REND/"))

    # --- recolección (HU-18) ---

    def test_collect_picks_up_the_collectors_payments(self):
        """La rendición junta los cobros publicados del cobrador (HU-18)."""
        payment = self._pay(10000.0)
        settlement = self._settlement()
        settlement.action_collect()
        self.assertIn(payment, settlement.payment_ids)
        self.assertEqual(settlement.amount_expected, 10000.0)
        self.assertEqual(settlement.payment_count, 1)

    def test_collect_ignores_another_collectors_payments(self):
        other = self.env["res.users"].create({
            "name": "Otro Cobrador Rendición",
            "login": "cvi_collector_settlement_other",
            "email": "other_settlement@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        mine = self._pay(10000.0)
        theirs = self._pay(5000.0, user=other)
        settlement = self._settlement()
        settlement.action_collect()
        self.assertIn(mine, settlement.payment_ids)
        self.assertNotIn(theirs, settlement.payment_ids)

    def test_commission_never_enters_a_settlement(self):
        """La comisión del vendedor no se rinde: por RN-01 es plata suya.

        Importa desde que el perfil híbrido hace que todo vendedor sea también
        cobrador: sin esta exclusión, el sistema le reclamaría su propia comisión.
        """
        commission = self.card.payment_ids.filtered("is_commission")
        if not commission:
            self.card.action_charge_first_installment()
            commission = self.card.payment_ids.filtered("is_commission")
        settlement = self._settlement(collector=self.vendor_user)
        settlement.action_collect()
        self.assertNotIn(commission, settlement.payment_ids)

    def test_late_payment_enters_the_next_open_settlement(self):
        """Un cobro con fecha vieja no queda huérfano: cae en la próxima rendición."""
        late = self._pay(3000.0, date="2026-01-20")
        settlement = self._settlement("2026-02-28", "monthly")
        settlement.action_collect()
        self.assertIn(late, settlement.payment_ids)
        self.assertEqual(settlement.late_payment_count, 1)

    def test_payment_after_the_close_is_left_out(self):
        self._pay(3000.0, date="2026-03-05")
        settlement = self._settlement("2026-02-28", "monthly")
        settlement.action_collect()
        self.assertFalse(settlement.payment_ids)

    def test_a_payment_is_only_settled_once(self):
        payment = self._pay(10000.0)
        first = self._settlement()
        first.action_collect()
        first.amount_delivered = 10000.0
        first.action_submit()
        second = self._settlement("2026-03-31")
        second.action_collect()
        self.assertNotIn(payment, second.payment_ids)
        self.assertEqual(payment.settlement_id, first)

    def test_cancelled_payment_is_not_expected(self):
        payment = self._pay(10000.0)
        payment.action_cancel()
        settlement = self._settlement()
        settlement.action_collect()
        self.assertEqual(settlement.amount_expected, 0.0)

    # --- entrega y diferencia (HU-19) ---

    def test_submit_collects_and_changes_state(self):
        self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 10000.0
        settlement.action_submit()
        self.assertEqual(settlement.state, "submitted")
        self.assertEqual(settlement.amount_expected, 10000.0)

    def test_difference_is_computed_against_what_was_expected(self):
        self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 9000.0
        settlement.action_submit()
        self.assertEqual(settlement.amount_difference, -1000.0)
        self.assertTrue(settlement.has_difference)

    def test_no_difference_when_the_cash_matches(self):
        self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 10000.0
        settlement.action_submit()
        self.assertFalse(settlement.has_difference)

    def test_cannot_submit_without_payments(self):
        settlement = self._settlement()
        with self.assertRaises(UserError):
            settlement.action_submit()

    # --- aprobación (HU-20) ---

    def test_manager_approves_a_matching_settlement(self):
        self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 10000.0
        settlement.action_submit()
        settlement.action_approve()
        self.assertEqual(settlement.state, "approved")
        self.assertEqual(settlement.approved_by_id, self.env.user)
        self.assertTrue(settlement.approved_date)

    def test_a_difference_cannot_be_approved_plainly(self):
        self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 9000.0
        settlement.action_submit()
        with self.assertRaises(UserError):
            settlement.action_approve()

    def test_flagging_a_difference_requires_an_explanation(self):
        self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 9000.0
        settlement.action_submit()
        with self.assertRaises(UserError):
            settlement.action_flag_difference()
        settlement.note = "Faltante que el cobrador repone mañana."
        settlement.action_flag_difference()
        self.assertEqual(settlement.state, "difference")

    def test_reset_draft_releases_the_payments(self):
        payment = self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 10000.0
        settlement.action_submit()
        settlement.action_reset_draft()
        self.assertEqual(settlement.state, "draft")
        self.assertFalse(payment.settlement_id)
        self.assertFalse(settlement.approved_by_id)

    # --- integridad ---

    def test_settled_payment_cannot_be_cancelled(self):
        """Anular un cobro ya rendido dejaría la rendición cuadrando contra nada."""
        payment = self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 10000.0
        settlement.action_submit()
        with self.assertRaises(UserError):
            payment.action_cancel()

    def test_reopening_allows_cancelling_again(self):
        payment = self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 10000.0
        settlement.action_submit()
        settlement.action_reset_draft()
        payment.action_cancel()
        self.assertEqual(payment.state, "cancel")

    def test_submitted_settlement_cannot_be_deleted(self):
        self._pay(10000.0)
        settlement = self._settlement()
        settlement.amount_delivered = 10000.0
        settlement.action_submit()
        with self.assertRaises(UserError):
            settlement.unlink()

    def test_collector_sees_only_his_own_settlements(self):
        """RN-07 también vale para las rendiciones."""
        mine = self._settlement()
        other = self.env["res.users"].create({
            "name": "Cobrador Ajeno Rendición",
            "login": "cvi_collector_settlement_foreign",
            "email": "foreign_settlement@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        theirs = self._settlement(collector=other)
        visible = self.env["cvi.settlement"].with_user(self.collector_user).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)
