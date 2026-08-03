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

    def _payment(self, mp_id="170951482351", amount=1500.0):
        """Crea un pago disponible en la bandeja de esta caja."""
        return self.Inbox.create({
            "mp_payment_id": mp_id, "account_id": self.account.id, "amount": amount,
            "date_approved": fields.Datetime.now(), "source": "qr",
            "mp_pos_id": "64365871", "state": "available",
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
        self.assertIn("ya fue asignado", second["error"])
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

        other_account = self.env["mercadopago.account"].create({
            "name": "Otra cuenta", "mode": "production", "mp_user_id": "999999999",
        })
        other_method = self.method.copy({
            "name": "MP QR otra caja", "mp_account_id": other_account.id,
        })
        self.assertFalse(other_method.revert_mp_reservation_by_uuid("uuid-abc")["ok"])
        self.assertEqual(payment.state, "matched")

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
