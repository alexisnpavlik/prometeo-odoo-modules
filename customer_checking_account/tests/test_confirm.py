# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError

from .common import CcaCommon


class TestConfirm(CcaCommon):

    def _withdrawal(self, product=None, qty=2, partner=None, **vals):
        """Retiro en borrador listo para confirmar."""
        values = {
            "partner_id": (partner or self.partner).id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "line_ids": [(0, 0, {"product_id": (product or self.product).id, "quantity": qty})],
        }
        values.update(vals)
        return self.env["cca.withdrawal"].create(values)

    def test_confirm_requires_dni(self):
        """Sin DNI en el contacto no se puede confirmar."""
        partner = self.env["res.partner"].create({"name": "Sin DNI"})
        withdrawal = self._withdrawal(partner=partner)
        with self.assertRaisesRegex(UserError, "DNI"):
            withdrawal.action_confirm()

    def test_confirm_requires_lines(self):
        """Un retiro sin líneas no se confirma."""
        withdrawal = self.env["cca.withdrawal"].create({"partner_id": self.partner.id})
        with self.assertRaises(UserError):
            withdrawal.action_confirm()

    def test_confirm_validates_picking_and_moves_state(self):
        """Confirmar deja el albarán validado y el retiro pendiente."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(withdrawal.picking_id.state, "done")
        self.assertEqual(withdrawal.picking_id.move_ids.quantity, 2.0)
        self.assertEqual(withdrawal.amount_residual, 200.0)

    def test_confirm_without_stock_validates_picking(self):
        """Sin stock disponible el albarán igual se valida (stock negativo)."""
        withdrawal = self._withdrawal(qty=50)
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.picking_id.state, "done")

    def test_confirm_service_only_no_picking(self):
        """Solo servicios: confirma sin albarán."""
        withdrawal = self._withdrawal(product=self.service, qty=1)
        withdrawal.action_confirm()
        self.assertFalse(withdrawal.picking_id)
        self.assertEqual(withdrawal.state, "pending")

    def test_confirm_freezes_lines_and_financing(self):
        """Confirmado, no se tocan líneas ni financiación."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.write({"line_ids": [(1, withdrawal.line_ids.id, {"quantity": 9})]})
        with self.assertRaises(UserError):
            withdrawal.surcharge_percent = 5.0

    def test_limit_block_raises(self):
        """Modo bloqueo: superar el límite impide confirmar."""
        withdrawal = self._withdrawal()
        withdrawal.account_id.write({"credit_limit": 100.0, "limit_mode": "block"})
        with self.assertRaisesRegex(UserError, "límite"):
            withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "draft")

    def test_limit_warn_confirms_and_notifies(self):
        """Modo advertencia: confirma y devuelve una notificación."""
        withdrawal = self._withdrawal()
        withdrawal.account_id.write({"credit_limit": 100.0, "limit_mode": "warn"})
        result = withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(result["tag"], "display_notification")

    def test_cancel_returns_stock(self):
        """Cancelar un retiro sin pagos genera y valida la devolución."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        withdrawal.action_cancel()
        self.assertEqual(withdrawal.state, "cancel")
        self.assertEqual(withdrawal.return_picking_id.state, "done")
        self.assertFalse(withdrawal.installment_ids)

    def test_draft_from_cancel_regenerates_preview(self):
        """Volver a borrador desde cancelado regenera las cuotas como vista previa."""
        withdrawal = self._withdrawal(installment_count=2)
        withdrawal.action_confirm()
        withdrawal.action_cancel()
        withdrawal.action_draft()
        self.assertEqual(withdrawal.state, "draft")
        self.assertEqual(len(withdrawal.installment_ids), 2)
        self.assertFalse(withdrawal.picking_id)

    def test_draft_only_from_cancel(self):
        """No se puede volver a borrador un retiro confirmado."""
        withdrawal = self._withdrawal()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.action_draft()
