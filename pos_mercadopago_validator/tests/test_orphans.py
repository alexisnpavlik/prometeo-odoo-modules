from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrphans(TransactionCase):
    """Bandeja de huérfanos y aviso de cierre de sesión.

    Un pago acreditado que sale de la ventana sin imputarse es dinero real
    que entró sin venta asociada: sigue en `available` (nunca cambia de
    estado) y tiene que aparecer listado, no esconderse.
    """

    def setUp(self):
        """Arma cuenta y método en una compañía activa, explícita.

        En esta base la compañía del superusuario (id 1) está archivada: un
        método de pago creado con ella no es legible por ningún usuario de
        prueba (mismo patrón que `test_aprobacion_manual.py`).
        """
        super().setUp()
        self.company = self.env["res.company"].search([], limit=1)
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=self.company.ids))
        self.account = self.env["mercadopago.account"].with_company(self.company).create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
            "company_id": self.company.id,
        })
        journal = self.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", self.company.id),
        ], limit=1)
        self.method = self.env["pos.payment.method"].with_company(self.company).create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
            "company_id": self.company.id,
        })
        self.config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja A", "company_id": self.company.id,
        })
        self.config.write({"payment_method_ids": [(4, self.method.id)]})
        self.config.open_ui()
        self.session = self.config.current_session_id
        # `open_ui()` sólo crea la sesión en 'opening_control': `start_at` no
        # se completa hasta que el cajero confirma el conteo de apertura, el
        # mismo paso que hace la interfaz real antes de vender.
        self.session.set_opening_control(0, "")

    def test_payment_outside_window_stays_available(self):
        """Salir de la ventana no cambia el estado: sigue disponible y es huérfano."""
        old = self.env["mercadopago.payment"].create({
            "mp_payment_id": "111", "account_id": self.account.id, "amount": 1500.0,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": "2020-01-01 10:00:00", "source": "qr",
            "mp_pos_id": "64365871", "state": "available",
        })
        self.assertEqual(old.state, "available")
        self.assertNotIn(
            old.id, [l["id"] for l in self.method.get_mp_inbox(1500.0)["matching"]]
        )

    def test_session_close_lists_unmatched_payments(self):
        """El cierre muestra los pagos sin imputar del período de la sesión."""
        self.env["mercadopago.payment"].create({
            "mp_payment_id": "222", "account_id": self.account.id, "amount": 900.0,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": fields.Datetime.now(), "source": "qr",
            "mp_pos_id": "64365871", "state": "available",
        })
        unmatched = self.session.get_mercadopago_unmatched()
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["mp_payment_id"], "222")

    def test_matched_payment_not_listed(self):
        """Un pago ya imputado no es un huérfano: no aparece en el aviso."""
        payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "333", "account_id": self.account.id, "amount": 500.0,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": fields.Datetime.now(), "source": "qr",
            "mp_pos_id": "64365871", "state": "available",
        })
        order = self.env["pos.order"].create({
            "session_id": self.session.id, "amount_total": 500.0,
            "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
        })
        pos_payment = self.env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": self.method.id,
            "amount": 500.0,
        })
        payment.impute(pos_payment)
        unmatched = self.session.get_mercadopago_unmatched()
        self.assertEqual(unmatched, [])

    def test_payment_before_session_start_not_listed(self):
        """Un huérfano de otro turno no se le atribuye a esta sesión."""
        self.env["mercadopago.payment"].create({
            "mp_payment_id": "444", "account_id": self.account.id, "amount": 700.0,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": "2020-01-01 10:00:00", "source": "qr",
            "mp_pos_id": "64365871", "state": "available",
        })
        self.assertEqual(self.session.get_mercadopago_unmatched(), [])

    def test_misconfigured_method_without_mp_pos_id_does_not_leak_all_orphans(self):
        """Un método QR sin `mp_pos_id` no debe matchear pagos de otras cajas.

        `("mp_pos_id", "in", [...])` con un `False` en la lista matchea todos
        los pagos por alias -hallazgo de la Task 9-, así que el dominio tiene
        que armarse por método reusando `_channel_domain()`, no juntando los
        `mp_pos_id` de todos los métodos en una sola lista.
        """
        other_method = self.env["pos.payment.method"].with_company(self.company).create({
            "name": "MP mal configurado",
            "journal_id": self.method.journal_id.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": False,
            "company_id": self.company.id,
        })
        other_config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja B", "company_id": self.company.id,
        })
        other_config.write({"payment_method_ids": [(4, other_method.id)]})
        other_config.open_ui()
        other_session = other_config.current_session_id

        self.env["mercadopago.payment"].create({
            "mp_payment_id": "555", "account_id": self.account.id, "amount": 300.0,
            "currency_id": self.account.company_id.currency_id.id,
            "date_approved": fields.Datetime.now(), "source": "qr",
            "mp_pos_id": "64365871", "state": "available",
        })
        self.assertEqual(other_session.get_mercadopago_unmatched(), [])

    def test_no_mercadopago_methods_returns_empty(self):
        """Una caja sin método de Mercado Pago no rompe el cierre."""
        plain_config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja sin MP", "company_id": self.company.id,
        })
        plain_config.open_ui()
        self.assertEqual(plain_config.current_session_id.get_mercadopago_unmatched(), [])
