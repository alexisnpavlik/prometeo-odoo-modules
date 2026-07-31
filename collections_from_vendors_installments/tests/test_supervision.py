# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSupervision(CviCommon):

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 3650
        self.supervisor = self.env["res.users"].create({
            "name": "Supervisor Test",
            "login": "cvi_supervisor_test",
            "email": "supervisor@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_supervisor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    def _assign(self, date_start="2026-01-01", date_end=False, collector=None):
        return self.env["cvi.supervision.assignment"].create({
            "supervisor_id": self.supervisor.id,
            "collector_id": (collector or self.collector_user).id,
            "date_start": date_start,
            "date_end": date_end,
        })

    def _visit(self):
        return self.env["cvi.supervision.visit"].create({
            "supervisor_id": self.supervisor.id,
            "collector_id": self.collector_user.id,
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        })

    # --- asignación (HU-21) ---

    def test_assignment_makes_the_collector_supervised(self):
        self._assign()
        self.assertIn(
            self.collector_user, self.supervisor.cvi_supervised_collector_ids
        )

    def test_expired_assignment_stops_counting_on_its_own(self):
        """La vigencia se evalúa contra hoy, no se guarda: vence sola (HU-21)."""
        self._assign(date_start="2020-01-01", date_end="2020-12-31")
        self.supervisor.invalidate_recordset(["cvi_supervised_collector_ids"])
        self.assertNotIn(
            self.collector_user, self.supervisor.cvi_supervised_collector_ids
        )

    def test_future_assignment_does_not_count_yet(self):
        self._assign(date_start="2099-01-01")
        self.supervisor.invalidate_recordset(["cvi_supervised_collector_ids"])
        self.assertNotIn(
            self.collector_user, self.supervisor.cvi_supervised_collector_ids
        )

    def test_assignment_cannot_end_before_it_starts(self):
        with self.assertRaises(ValidationError):
            self._assign(date_start="2026-06-01", date_end="2026-01-01")

    def test_nobody_supervises_himself(self):
        with self.assertRaises(ValidationError):
            self.env["cvi.supervision.assignment"].create({
                "supervisor_id": self.supervisor.id,
                "collector_id": self.supervisor.id,
                "date_start": "2026-01-01",
            })

    # --- visibilidad (HU-21) ---

    def test_supervisor_sees_the_portfolio_he_was_assigned(self):
        """El supervisor solo ve la cartera que le corresponde (HU-21).

        Con with_user y no como el usuario de tests, que es superusuario y saltearía
        las ir.rule por completo.
        """
        self._assign()
        visible = self.env["cvi.card"].with_user(self.supervisor).search([])
        self.assertIn(self.card, visible)

    def test_supervisor_sees_nothing_without_an_assignment(self):
        visible = self.env["cvi.card"].with_user(self.supervisor).search([])
        self.assertNotIn(self.card, visible)

    def test_supervisor_does_not_see_an_unassigned_collectors_portfolio(self):
        other_collector = self.env["res.users"].create({
            "name": "Cobrador No Supervisado",
            "login": "cvi_collector_unsupervised",
            "email": "unsupervised@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        other_card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": other_collector.id,
        })
        other_card.action_confirm()
        self._assign()
        visible = self.env["cvi.card"].with_user(self.supervisor).search([])
        self.assertIn(self.card, visible)
        self.assertNotIn(other_card, visible)

    def test_supervisor_cannot_modify_a_card(self):
        """Auditar es mirar: el supervisor no toca la cartera."""
        self._assign()
        with self.assertRaises(Exception):
            self.card.with_user(self.supervisor).write({"charge_day_month": 20})

    # --- visita (HU-22) ---

    def test_visit_gets_a_sequence_reference(self):
        self.assertTrue(self._visit().name.startswith("SUP/"))

    def test_loading_cards_brings_the_collectors_portfolio(self):
        visit = self._visit()
        visit.action_load_cards()
        self.assertIn(self.card, visit.line_ids.mapped("card_id"))

    def test_loading_twice_does_not_duplicate_lines(self):
        visit = self._visit()
        visit.action_load_cards()
        count = len(visit.line_ids)
        visit.action_load_cards()
        self.assertEqual(len(visit.line_ids), count)

    def test_result_is_compliant_without_issues(self):
        visit = self._visit()
        visit.action_load_cards()
        visit.line_ids.write({"verified": True})
        self.assertEqual(visit.result, "compliant")

    def test_one_issue_makes_the_whole_visit_flagged(self):
        visit = self._visit()
        visit.action_load_cards()
        visit.line_ids[0].write({"has_issue": True, "note": "El cliente niega el pago."})
        self.assertEqual(visit.result, "issues")
        self.assertEqual(visit.issue_count, 1)

    def test_an_issue_needs_an_explanation(self):
        """Una observación sin texto no le sirve a nadie que lea la visita después."""
        visit = self._visit()
        visit.action_load_cards()
        with self.assertRaises(ValidationError):
            visit.line_ids[0].write({"has_issue": True})

    def test_closing_records_the_result(self):
        visit = self._visit()
        visit.action_load_cards()
        visit.line_ids.write({"verified": True})
        visit.action_close()
        self.assertEqual(visit.state, "done")

    def test_cannot_close_an_empty_visit(self):
        visit = self._visit()
        with self.assertRaises(UserError):
            visit.action_close()

    def test_closed_visit_can_be_reopened(self):
        visit = self._visit()
        visit.action_load_cards()
        visit.action_close()
        visit.action_reopen()
        self.assertEqual(visit.state, "draft")

    def test_period_cannot_end_before_it_starts(self):
        with self.assertRaises(ValidationError):
            self.env["cvi.supervision.visit"].create({
                "supervisor_id": self.supervisor.id,
                "collector_id": self.collector_user.id,
                "date_from": "2026-12-31",
                "date_to": "2026-01-01",
            })
