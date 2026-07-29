# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CawCommon


@tagged("post_install", "-at_install")
class TestCawWithdrawal(CawCommon):

    def _new_withdrawal(self, lines=None):
        """Crea un retiro en borrador con las líneas indicadas."""
        self.partner.caw_enabled = True
        lines = lines or [(2.0, 150.0), (1.0, 300.0)]
        return self.env["caw.withdrawal"].create({
            "partner_id": self.partner.id,
            "line_ids": [
                (0, 0, {
                    "product_id": self.product.id,
                    "quantity": qty,
                    "price_unit": price,
                })
                for qty, price in lines
            ],
        })

    def test_amount_total_sums_lines(self):
        """El total del retiro es la suma de los subtotales de sus líneas."""
        withdrawal = self._new_withdrawal()
        self.assertEqual(withdrawal.line_ids[0].price_subtotal, 300.0)
        self.assertEqual(withdrawal.line_ids[1].price_subtotal, 300.0)
        self.assertEqual(withdrawal.amount_total, 600.0)

    def test_account_is_assigned_from_partner(self):
        """Al crear el retiro se resuelve la cuenta corriente del partner."""
        withdrawal = self._new_withdrawal()
        self.assertTrue(withdrawal.account_id)
        self.assertEqual(withdrawal.account_id.partner_id, self.partner)
        self.assertEqual(withdrawal.account_id.company_id, withdrawal.company_id)

    def test_name_comes_from_sequence(self):
        """El retiro toma su número de la secuencia propia del módulo."""
        withdrawal = self._new_withdrawal()
        self.assertNotEqual(withdrawal.name, "/")
        self.assertTrue(withdrawal.name.startswith("CC/"))

    def test_starts_in_draft(self):
        """Un retiro nace en borrador."""
        self.assertEqual(self._new_withdrawal().state, "draft")

    def test_disabled_partner_is_rejected(self):
        """No se puede crear un retiro para un contacto sin cuenta corriente habilitada."""
        from odoo.exceptions import UserError
        other = self.env["res.partner"].create({"name": "No habilitado"})
        with self.assertRaises(UserError):
            self.env["caw.withdrawal"].create({"partner_id": other.id})

    def test_line_write_blocked_after_confirm(self):
        """Una vez confirmado el retiro, no se puede editar una línea directamente."""
        from odoo.exceptions import UserError
        withdrawal = self._new_withdrawal()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.line_ids.write({"price_unit": 999.0})

    def test_line_unlink_blocked_after_confirm(self):
        """Una vez confirmado el retiro, no se puede borrar una línea directamente."""
        from odoo.exceptions import UserError
        withdrawal = self._new_withdrawal()
        withdrawal.action_confirm()
        with self.assertRaises(UserError):
            withdrawal.line_ids[0].unlink()

    def test_line_create_blocked_after_confirm(self):
        """Una vez confirmado el retiro, no se puede crear una línea nueva apuntando a él."""
        from odoo.exceptions import UserError
        withdrawal = self._new_withdrawal()
        withdrawal.action_confirm()
        total_before = withdrawal.amount_total
        with self.assertRaises(UserError):
            self.env["caw.withdrawal.line"].create({
                "withdrawal_id": withdrawal.id,
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 999.0,
            })
        withdrawal.invalidate_recordset()
        self.assertEqual(withdrawal.amount_total, total_before)

    def test_line_reassign_to_confirmed_withdrawal_is_blocked(self):
        """No se puede reasignar una línea de un borrador hacia un retiro ya confirmado."""
        from odoo.exceptions import UserError
        draft = self._new_withdrawal(lines=[(1.0, 50.0)])
        confirmed = self._new_withdrawal()
        confirmed.action_confirm()
        total_before = confirmed.amount_total
        with self.assertRaises(UserError):
            draft.line_ids.write({"withdrawal_id": confirmed.id})
        confirmed.invalidate_recordset()
        self.assertEqual(confirmed.amount_total, total_before)

    def test_onchange_partner_id_preloads_account(self):
        """Elegir el contacto precarga account_id en el registro en memoria (new).

        Bug real detectado en uso: account_id se resuelve en create(), pero el
        cliente web valida los campos obligatorios ANTES de llamar a create(). Sin
        este onchange, account_id (required=True) queda vacío y el alta nunca
        progresa desde la UI, aunque los tests que llaman a create() directamente
        por ORM nunca lo detectan. account_id tiene groups="base.group_no_one" en
        la vista, así que se verifica a nivel de modelo (new + onchange) en vez de
        con Form, que no puede ver un campo ausente del arch renderizado.
        """
        self.partner.caw_enabled = True
        withdrawal = self.env["caw.withdrawal"].new({})
        withdrawal.partner_id = self.partner
        withdrawal._onchange_partner_id()
        self.assertTrue(withdrawal.account_id)
        self.assertEqual(withdrawal.account_id.partner_id, self.partner)

    def _cc_user(self, login="caw_operator_withdrawal_test"):
        """Crea un usuario con solo el grupo Operador (sin Manager)."""
        return self.env["res.users"].create({
            "name": "Operador CC Test",
            "login": login,
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("checking_account_withdrawals.group_cc_user").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def test_operator_can_read_caw_enabled_and_create_withdrawal(self):
        """Un Operador (sin Manager) puede leer caw_enabled y crear un retiro normal.

        Hallazgo re-revisión: `groups=` en el campo bloqueaba también la lectura, y
        _caw_resolve_account/_onchange_partner_id/_caw_check_confirmable la necesitan
        para dejar operar sobre un contacto ya habilitado.
        """
        self.partner.caw_enabled = True
        user = self._cc_user()
        partner_as_user = self.partner.with_user(user)
        self.assertTrue(partner_as_user.caw_enabled)
        withdrawal = self.env["caw.withdrawal"].with_user(user).create({
            "partner_id": self.partner.id,
            "line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1.0,
                "price_unit": 100.0,
            })],
        })
        self.assertTrue(withdrawal)
        self.assertEqual(withdrawal.partner_id, self.partner)
        self.assertEqual(withdrawal.amount_total, 100.0)

    def test_operator_cannot_enable_partner(self):
        """Un Operador no puede habilitar/deshabilitar la cuenta corriente de un contacto."""
        from odoo.exceptions import AccessError
        user = self._cc_user()
        with self.assertRaises(AccessError):
            self.partner.with_user(user).write({"caw_enabled": True})

    def test_manager_can_enable_partner(self):
        """Un Manager sí puede habilitar la cuenta corriente de un contacto sin error."""
        other = self.env["res.partner"].create({"name": "Otro Fiado Test"})
        other.write({"caw_enabled": True})
        self.assertTrue(other.caw_enabled)
