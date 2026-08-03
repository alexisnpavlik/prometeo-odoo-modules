from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReservaPorUuid(TransactionCase):
    """Reserva y deshacer contra una línea de cobro que sólo vive en el navegador."""

    def setUp(self):
        """Arma una cuenta, un método de cobro de este módulo y su bandeja."""
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        self.Inbox = self.env["mercadopago.payment"]

    def _payment(self, mp_id="170951482351", amount=1500.0, account=None,
                 pos_id="64365871", minutes_ago=0):
        """Crea un pago disponible, por omisión en la bandeja de esta caja."""
        return self.Inbox.create({
            "mp_payment_id": mp_id,
            "account_id": (account or self.account).id,
            "amount": amount,
            "date_approved": fields.Datetime.subtract(
                fields.Datetime.now(), minutes=minutes_ago
            ),
            "source": "qr", "mp_pos_id": pos_id, "state": "available",
        })

    def _pos_user(self, login):
        """Crea otro cajero real, con el grupo del POS y una compañía activa."""
        # En esta base la compañía del entorno puede estar archivada.
        active_company = self.env["res.company"].search([], limit=1)
        return self.env["res.users"].create({
            "name": login, "login": login,
            "company_id": active_company.id,
            "company_ids": [(6, 0, active_company.ids)],
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("point_of_sale.group_pos_user").id,
            ])],
        })

    def _make_pos_payment(self, amount=1500.0):
        """Crea una línea de cobro real sobre la que imputar."""
        config = self.env["pos.config"].create({"name": "Caja test reserva uuid"})
        config.write({"payment_method_ids": [(4, self.method.id)]})
        config.open_ui()
        order = self.env["pos.order"].create({
            "session_id": config.current_session_id.id, "amount_total": amount,
            "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
        })
        return self.env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": self.method.id, "amount": amount,
        })

    def test_reserve_marks_the_payment_and_keeps_the_uuid(self):
        """La reserva deja el pago fuera de la bandeja, todavía sin pos.payment."""
        payment = self._payment()
        result = self.method.impute_mp_payment_by_uuid(payment.id, "uuid-abc")
        self.assertEqual(result, {"ok": True, "mp_payment_id": "170951482351"})
        self.assertEqual(payment.state, "matched")
        self.assertEqual(payment.pos_payment_uuid, "uuid-abc")
        self.assertFalse(payment.pos_payment_id)
        self.assertEqual(payment.matched_by_user_id, self.env.user)
        self.assertEqual(self.method.get_mp_inbox(1500.0)["matching"], [])

    def test_second_reserve_loses_the_race_without_raising(self):
        """El segundo cajero recibe el error de negocio, no una excepción."""
        payment = self._payment()
        self.assertTrue(self.method.impute_mp_payment_by_uuid(payment.id, "uuid-a")["ok"])

        second = self.method.impute_mp_payment_by_uuid(payment.id, "uuid-b")
        self.assertFalse(second["ok"])
        self.assertIn("Actualizá la lista", second["error"])
        self.assertEqual(payment.pos_payment_uuid, "uuid-a")

    def test_undo_returns_the_payment_to_the_inbox(self):
        """Deshacer libera el pago y borra la reserva por uuid."""
        payment = self._payment()
        self.method.impute_mp_payment_by_uuid(payment.id, "uuid-abc")

        self.assertEqual(self.method.revert_mp_reservation_by_uuid("uuid-abc"), {"ok": True})
        self.assertEqual(payment.state, "available")
        self.assertFalse(payment.pos_payment_uuid)
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 1)

    def test_undo_of_an_unknown_uuid_is_reported_not_raised(self):
        """Un uuid sin reserva devuelve un error legible para el cajero."""
        result = self.method.revert_mp_reservation_by_uuid("uuid-que-no-existe")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_reservations_of_other_accounts_are_out_of_reach(self):
        """El uuid viene del navegador: no debe alcanzar la bandeja de otra cuenta."""
        payment = self._payment()
        self.method.impute_mp_payment_by_uuid(payment.id, "uuid-abc")

        other_method = self._other_account_method()
        self.assertFalse(other_method.revert_mp_reservation_by_uuid("uuid-abc")["ok"])
        self.assertEqual(payment.state, "matched")

    def _other_account_method(self):
        """Un método de cobro idéntico pero apuntando a otra cuenta."""
        other_account = self.env["mercadopago.account"].create({
            "name": "Otra cuenta", "mode": "production", "mp_user_id": "999999999",
        })
        return self.method.copy({
            "name": "MP QR otra caja", "mp_account_id": other_account.id,
        })

    def test_reserving_a_payment_of_another_account_is_rejected(self):
        """El id de la fila llega del navegador: no alcanza bandejas de otra cuenta."""
        other_method = self._other_account_method()
        payment = self._payment()  # vive en la cuenta de self.method

        result = other_method.impute_mp_payment_by_uuid(payment.id, "uuid-abc")
        self.assertFalse(result["ok"])
        self.assertIn("Actualizá la lista", result["error"])
        self.assertEqual(payment.state, "available")
        self.assertFalse(payment.pos_payment_uuid)

    def test_reserving_a_payment_of_another_cash_register_is_rejected(self):
        """Misma cuenta, otro QR: tampoco se puede tomar el pago de la caja de al lado."""
        payment = self._payment(pos_id="99999999")

        result = self.method.impute_mp_payment_by_uuid(payment.id, "uuid-abc")
        self.assertFalse(result["ok"])
        self.assertEqual(payment.state, "available")

    def test_reserving_a_payment_outside_the_window_is_rejected(self):
        """Lo que el cajero no pudo ver en la lista tampoco lo puede tomar."""
        self.assertEqual(self.method.search_window_minutes, 5)
        payment = self._payment(minutes_ago=30)

        result = self.method.impute_mp_payment_by_uuid(payment.id, "uuid-abc")
        self.assertFalse(result["ok"])
        self.assertEqual(payment.state, "available")

    def test_imputing_a_payment_of_another_cash_register_is_rejected(self):
        """La misma puerta cierra en la RPC con pos.payment real, no sólo por uuid."""
        payment = self._payment(pos_id="99999999")
        line = self._make_pos_payment(1500.0)

        result = self.method.impute_mp_payment(payment.id, line.id)
        self.assertFalse(result["ok"])
        self.assertIn("Actualizá la lista", result["error"])
        self.assertEqual(payment.state, "available")
        self.assertFalse(line.mercadopago_payment_id)

    def test_another_cashier_cannot_steal_a_live_reservation(self):
        """Quien no hizo la reserva no la puede liberar para quedársela."""
        payment = self._payment()
        self.method.impute_mp_payment_by_uuid(payment.id, "uuid-abc")

        thief = self._pos_user("cajero_ajeno_mp_reserva")
        result = self.method.with_user(thief).revert_mp_reservation_by_uuid("uuid-abc")
        self.assertFalse(result["ok"])
        self.assertIn("otro cajero", result["error"])
        self.assertEqual(payment.state, "matched")
        self.assertEqual(payment.pos_payment_uuid, "uuid-abc")

    def test_the_cashier_cannot_read_the_reservation_uuid(self):
        """`pos_payment_uuid` no está al alcance del cajero: sin él no hay robo."""
        payment = self._payment()
        self.method.impute_mp_payment_by_uuid(payment.id, "uuid-abc")

        cashier = self._pos_user("cajero_curioso_mp_reserva")
        with self.assertRaises(AccessError):
            payment.with_user(cashier).read(["pos_payment_uuid"])

    def test_two_reservations_on_the_same_uuid_are_rejected(self):
        """Dos pagos reservados contra el mismo uuid dejarían uno huérfano."""
        first = self._payment("111", 1500.0)
        second = self._payment("222", 1500.0)
        self.assertTrue(self.method.impute_mp_payment_by_uuid(first.id, "uuid-abc")["ok"])

        result = self.method.impute_mp_payment_by_uuid(second.id, "uuid-abc")
        self.assertFalse(result["ok"])
        self.assertIn("111", result["error"])
        self.assertEqual(second.state, "available")

    def test_access_denied_for_user_outside_pos_group(self):
        """Sin point_of_sale.group_pos_user no se reserva ni se deshace."""
        # En esta base la compañía del entorno puede estar archivada: se elige
        # una activa explícitamente en vez de asumir self.env.company.
        active_company = self.env["res.company"].search([], limit=1)
        outsider = self.env["res.users"].create({
            "name": "Sin acceso a POS", "login": "sin_acceso_mp_reserva",
            "company_id": active_company.id,
            "company_ids": [(6, 0, active_company.ids)],
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.method.with_user(outsider).impute_mp_payment_by_uuid(1, "uuid-x")
        with self.assertRaises(AccessError):
            self.method.with_user(outsider).revert_mp_reservation_by_uuid("uuid-x")
