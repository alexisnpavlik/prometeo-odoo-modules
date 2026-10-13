# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError

from .common import CcaCommon


class TestEdit(CcaCommon):

    def _confirmed(self, product=None, qty=2, count=2):
        """Retiro confirmado con fecha pasada para poder mover vencimientos hacia atrás."""
        withdrawal = self.env["cca.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "installment_count": count,
            "line_ids": [(0, 0, {"product_id": (product or self.service).id, "quantity": qty})],
        })
        withdrawal.action_confirm()
        return withdrawal

    def test_edit_without_payments_returns_to_draft(self):
        """Sin pagos, Editar devuelve el stock y deja el retiro en borrador para cambiar todo."""
        withdrawal = self._confirmed(product=self.product, qty=2)
        first_picking = withdrawal.picking_id
        withdrawal.action_edit()
        self.assertEqual(withdrawal.state, "draft")
        self.assertFalse(withdrawal.picking_id)
        self.assertEqual(withdrawal.return_picking_id.state, "done")
        self.assertEqual(len(withdrawal.installment_ids), 2)
        withdrawal.write({"line_ids": [(1, withdrawal.line_ids.id, {"quantity": 3})], "installment_count": 3})
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(withdrawal.amount_total, 300.0)
        self.assertEqual(len(withdrawal.installment_ids), 3)
        self.assertNotEqual(withdrawal.picking_id, first_picking)
        self.assertEqual(withdrawal.picking_id.state, "done")

    def test_edit_with_payments_only_due_dates(self):
        """Con pagos, Editar habilita solo los vencimientos."""
        withdrawal = self._confirmed()
        self.env["cca.payment"].create({"partner_id": self.partner.id, "amount": 30})
        withdrawal.action_edit()
        self.assertEqual(withdrawal.state, "partial")
        self.assertTrue(withdrawal.edit_due_dates)
        second = withdrawal.installment_ids.sorted("sequence")[1]
        withdrawal.write({"installment_ids": [(1, second.id, {"date_due": date(2027, 6, 1)})]})
        self.assertEqual(second.date_due, date(2027, 6, 1))
        self.assertFalse(withdrawal.edit_due_dates)
        with self.assertRaises(UserError):
            withdrawal.write({"installment_ids": [(1, second.id, {"amount": 10})]})
        with self.assertRaises(UserError):
            withdrawal.write({"line_ids": [(1, withdrawal.line_ids.id, {"quantity": 9})]})

    def test_moving_due_date_to_past_marks_overdue(self):
        """Mover un vencimiento al pasado deja la cuota vencida."""
        withdrawal = self._confirmed()
        self.env["cca.payment"].create({"partner_id": self.partner.id, "amount": 10})
        withdrawal.action_edit()
        first = withdrawal.installment_ids.sorted("sequence")[0]
        withdrawal.write({"installment_ids": [(1, first.id, {"date_due": date(2026, 3, 1)})]})
        self.assertEqual(first.state, "overdue")
        self.assertTrue(withdrawal.is_overdue)

    def test_edit_not_allowed_on_draft_or_cancel(self):
        """Editar solo aplica a retiros confirmados."""
        withdrawal = self._confirmed()
        withdrawal.action_cancel()
        with self.assertRaises(UserError):
            withdrawal.action_edit()
