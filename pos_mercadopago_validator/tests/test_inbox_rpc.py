from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInboxRpc(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        self.journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        self.method = self.env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": self.journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        self.Inbox = self.env["mercadopago.payment"]

    def _payment(self, mp_id, amount, pos_id="64365871", source="qr"):
        return self.Inbox.create({
            "mp_payment_id": mp_id, "account_id": self.account.id, "amount": amount,
            "date_approved": fields_now(), "source": source, "mp_pos_id": pos_id,
            "state": "available",
        })

    def _make_pos_payment(self, amount=1500.0):
        """Crea una línea de cobro real sobre la que imputar, vía self.method."""
        config = self.env["pos.config"].create({"name": "Caja test inbox rpc"})
        config.write({"payment_method_ids": [(4, self.method.id)]})
        config.open_ui()
        session = config.current_session_id
        order = self.env["pos.order"].create({
            "session_id": session.id, "amount_total": amount, "amount_tax": 0,
            "amount_paid": 0, "amount_return": 0,
        })
        return self.env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": self.method.id, "amount": amount,
        })

    def test_only_this_cash_register_qr_is_listed(self):
        """Un pago del QR de otra caja no aparece en esta bandeja."""
        self._payment("111", 1500.0, pos_id="64365871")
        self._payment("222", 1500.0, pos_id="99999999")
        result = self.method.get_mp_inbox(1500.0)
        self.assertEqual([p["mp_payment_id"] for p in result["matching"]], ["111"])

    def test_non_matching_amounts_are_counted_not_listed(self):
        """Los montos distintos no se listan pero se cuentan."""
        self._payment("111", 1500.0)
        self._payment("333", 980.0)
        result = self.method.get_mp_inbox(1500.0)
        self.assertEqual(len(result["matching"]), 1)
        self.assertEqual(result["others_count"], 1)

    def test_alias_excluded_unless_enabled(self):
        """El canal alias sólo entra si el método lo habilita."""
        self._payment("444", 1500.0, pos_id=False, source="alias")
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 0)
        self.method.accept_alias_payments = True
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 1)

    def test_stale_flag_when_never_synced(self):
        """Sin sincronización exitosa, la bandeja se reporta desactualizada."""
        self.assertTrue(self.method.get_mp_inbox(1500.0)["stale"])

    def test_no_mp_pos_id_configured_does_not_leak_alias_payments(self):
        """Sin mp_pos_id configurado, la bandeja no debe filtrar por accidente
        los pagos por alias (que también llegan con mp_pos_id vacío)."""
        self.method.mp_pos_id = False
        self.assertFalse(self.method.accept_alias_payments)
        self._payment("777", 1500.0, pos_id=False, source="alias")
        result = self.method.get_mp_inbox(1500.0)
        self.assertEqual(result["matching"], [])
        self.assertEqual(result["others_count"], 0)

    def test_impute_mp_payment_links_and_returns_ok(self):
        """Imputación exitosa: vincula el pago y devuelve ok=True."""
        payment = self._payment("555", 1500.0)
        line = self._make_pos_payment(1500.0)
        result = self.method.impute_mp_payment(payment.id, line.id)
        self.assertEqual(result, {"ok": True, "mp_payment_id": "555"})
        self.assertEqual(payment.state, "matched")
        self.assertEqual(payment.pos_payment_id, line)

    def test_impute_mp_payment_returns_error_on_lost_race(self):
        """La carrera perdida se devuelve como {"ok": False, "error": ...}, sin excepción."""
        payment = self._payment("666", 1500.0)
        line_a = self._make_pos_payment(1500.0)
        line_b = self._make_pos_payment(1500.0)
        first = self.method.impute_mp_payment(payment.id, line_a.id)
        self.assertTrue(first["ok"])

        second = self.method.impute_mp_payment(payment.id, line_b.id)
        self.assertFalse(second["ok"])
        self.assertIn("error", second)
        self.assertEqual(payment.pos_payment_id, line_a)

    def test_access_denied_for_user_outside_pos_group(self):
        """Un usuario sin point_of_sale.group_pos_user no lee ni imputa la bandeja."""
        # self.env.company puede resolver a una compañía archivada en esta base
        # (gotcha de la instancia de pruebas, no de este módulo): se busca una
        # activa explícitamente en vez de asumir la del entorno.
        active_company = self.env["res.company"].search([], limit=1)
        outsider = self.env["res.users"].create({
            "name": "Sin acceso a POS", "login": "sin_acceso_mp_inbox_rpc",
            "company_id": active_company.id,
            "company_ids": [(6, 0, active_company.ids)],
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.method.with_user(outsider).get_mp_inbox(1500.0)
        with self.assertRaises(AccessError):
            self.method.with_user(outsider).impute_mp_payment(1, 1)


def fields_now():
    from odoo import fields
    return fields.Datetime.now()
