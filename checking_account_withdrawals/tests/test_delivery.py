# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawDelivery(CawCommon):
    """Flujo nuevo: el Operador entrega primero y el Manager arma las cuotas después."""

    def setUp(self):
        super().setUp()
        self.partner.caw_enabled = True
        self.company.caw_installment_count = 1
        self.company.caw_picking_type_id = self.warehouse.out_type_id
        self.account = self.env["caw.account"]._get_or_create(self.partner, self.company)

    def _draft(self, qty=2.0, price=100.0, product=None):
        """Retiro en borrador con una línea del producto indicado."""
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "date": "2026-01-01",
            "line_ids": [(0, 0, {
                "product_id": (product or self.product).id,
                "quantity": qty,
                "price_unit": price,
            })],
        })

    def _cc_user(self, login="caw_delivery_operator_test"):
        """Usuario Operador: group_cc_user sin group_cc_manager."""
        return self.env["res.users"].create({
            "name": "Operador CC Entrega",
            "login": login,
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("checking_account_withdrawals.group_cc_user").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def test_deliver_creates_and_validates_picking(self):
        """Entregar genera el albarán de salida y lo valida en un solo paso."""
        withdrawal = self._draft(qty=2.0)
        withdrawal.action_deliver()
        self.assertTrue(withdrawal.picking_id)
        self.assertEqual(withdrawal.picking_id.picking_type_id.code, "outgoing")
        self.assertEqual(withdrawal.picking_id.state, "done")

    def test_delivered_state_before_confirmation(self):
        """Entregado y sin confirmar: estado 'delivered', sin cuotas ni deuda."""
        withdrawal = self._draft()
        withdrawal.action_deliver()
        self.assertEqual(withdrawal.state, "delivered")
        self.assertFalse(withdrawal.installment_ids)
        self.assertEqual(withdrawal.amount_residual, 0.0)
        self.assertEqual(self.account.balance, 0.0)

    def test_operator_can_deliver(self):
        """El Operador puede entregar sin ser usuario de stock ni Manager."""
        withdrawal = self._draft()
        user = self._cc_user()
        withdrawal.with_user(user).action_deliver()
        self.assertEqual(withdrawal.state, "delivered")
        self.assertEqual(withdrawal.picking_id.state, "done")

    def test_confirm_after_delivery_generates_installments(self):
        """Confirmar un retiro entregado arma las cuotas y no duplica el albarán."""
        withdrawal = self._draft(qty=2.0, price=100.0)
        withdrawal.action_deliver()
        picking = withdrawal.picking_id
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertEqual(withdrawal.picking_id, picking)
        self.assertEqual(len(withdrawal.installment_ids), 1)
        self.assertEqual(withdrawal.amount_residual, 200.0)
        self.assertEqual(self.account.balance, 200.0)

    def test_confirm_without_delivery_still_creates_picking(self):
        """El flujo viejo sigue vivo: confirmar sin entregar genera el albarán sin validar."""
        withdrawal = self._draft()
        withdrawal.action_confirm()
        self.assertEqual(withdrawal.state, "pending")
        self.assertTrue(withdrawal.picking_id)
        self.assertNotEqual(withdrawal.picking_id.state, "done")

    def test_deliver_rejects_second_delivery(self):
        """No se puede entregar dos veces el mismo retiro."""
        withdrawal = self._draft()
        withdrawal.action_deliver()
        with self.assertRaises(UserError):
            withdrawal.action_deliver()

    def test_deliver_requires_storable_product(self):
        """Sin productos almacenables no hay mercadería que entregar."""
        service = self.env["product.product"].create({
            "name": "Servicio CC Test",
            "type": "service",
            "is_storable": False,
            "list_price": 50.0,
        })
        withdrawal = self._draft(product=service)
        with self.assertRaises(UserError):
            withdrawal.action_deliver()

    def test_delivered_lines_are_locked(self):
        """Entregado el retiro, las líneas no se pueden modificar."""
        withdrawal = self._draft()
        withdrawal.action_deliver()
        with self.assertRaises(UserError):
            withdrawal.write({"line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 10.0,
            })]})

    def test_delivered_withdrawal_can_be_cancelled(self):
        """Un entregado sin confirmar se puede cancelar; queda el aviso de devolución."""
        withdrawal = self._draft()
        withdrawal.action_deliver()
        withdrawal.action_cancel()
        self.assertEqual(withdrawal.state, "cancel")
        bodies = " ".join(withdrawal.message_ids.mapped("body"))
        self.assertIn("devolución", bodies.lower())

    def test_confirmed_and_delivered_cannot_be_cancelled(self):
        """Confirmado y con el stock ya entregado, la cancelación sigue bloqueada."""
        withdrawal = self._draft()
        withdrawal.action_deliver()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.action_cancel()

    def test_delivered_withdrawal_cannot_be_deleted(self):
        """Con el stock afuera, el retiro no se borra: hay que cancelarlo."""
        withdrawal = self._draft()
        withdrawal.action_deliver()
        with self.assertRaises(UserError):
            withdrawal.unlink()

    def test_validate_fails_loudly_on_unknown_wizard(self):
        """Si button_validate devuelve un diálogo que el módulo no sabe resolver, avisa.

        Regresión: con stock_sms activo, button_validate devuelve el wizard
        confirm.stock.sms; el módulo lo ignoraba y terminaba sin validar nada,
        dejando el retiro en borrador con el albarán en 'Listo' y sin ningún error.
        """
        withdrawal = self._draft()
        withdrawal._caw_create_picking()
        wizard_action = {
            "type": "ir.actions.act_window",
            "res_model": "confirm.stock.sms",
            "res_id": 1,
            "target": "new",
        }
        with patch.object(
            type(withdrawal.picking_id), "button_validate", lambda *a, **k: wizard_action
        ):
            with self.assertRaises(UserError):
                withdrawal.action_validate_picking()

    def test_validate_skips_sms_confirmation(self):
        """La validación pide saltear el aviso de SMS: no corresponde a un retiro a cuenta."""
        withdrawal = self._draft()
        withdrawal._caw_create_picking()
        picking_model = type(withdrawal.picking_id)
        original = picking_model.button_validate
        captured = {}

        def spy(picking, *args, **kwargs):
            captured["skip_sms"] = picking.env.context.get("skip_sms")
            return original(picking, *args, **kwargs)

        with patch.object(picking_model, "button_validate", spy):
            withdrawal.action_validate_picking()
        self.assertTrue(captured["skip_sms"])
        self.assertEqual(withdrawal.picking_id.state, "done")
