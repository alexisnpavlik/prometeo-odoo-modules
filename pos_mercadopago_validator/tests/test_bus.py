from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBusNotification(TransactionCase):
    def setUp(self):
        """Cuenta MP + método QR + una caja (Caja A) con sesión abierta."""
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
        self.config = self.env["pos.config"].create({"name": "Caja A"})
        self.config.write({"payment_method_ids": [(4, self.method.id)]})
        self.config.open_ui()

    def _spy_on_notify(self):
        """Devuelve (lista de config_ids notificados, contexto a usar con `with`)."""
        notified = []
        original = type(self.env["pos.config"])._notify

        def spy(self_config, *args, **kwargs):
            notified.append(self_config.id)
            return original(self_config, *args, **kwargs)

        return notified, patch.object(type(self.env["pos.config"]), "_notify", spy)

    def test_notifies_only_configs_with_that_qr(self):
        """El bus es por pos.config: sólo se notifica a la caja dueña del QR."""
        other_config = self.env["pos.config"].create({"name": "Caja B"})
        payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351", "account_id": self.account.id,
            "amount": 1500.0, "date_approved": "2026-08-03 15:21:49",
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })
        notified, patched = self._spy_on_notify()
        with patched:
            payment._notify_open_sessions()

        self.assertIn(self.config.id, notified)
        self.assertNotIn(other_config.id, notified)

    def test_notifies_alias_config_only_when_enabled(self):
        """Un pago por alias sólo notifica a la config con accept_alias_payments activo.

        Se arman configs propias (no self.config/self.method de setUp) porque
        una vez que una caja tiene sesión abierta, Odoo bloquea la edición de
        sus métodos de pago: accept_alias_payments se define en la creación.

        `payment_method_ids` se fija con reemplazo total `(6, 0, [...])`, no
        con `(4, id)`: pos.config.create() ya trae por default otros métodos
        de pago existentes en la compañía (incluido, acá, el método QR creado
        para la otra caja), y sumar con `(4, ...)` dejaría ambas cajas con el
        mismo método por accidente de setup, no por el criterio bajo prueba.
        """
        method_alias = self.env["pos.payment.method"].create({
            "name": "MP alias on", "journal_id": self.journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "accept_alias_payments": True,
        })
        config_alias = self.env["pos.config"].create({"name": "Caja alias on"})
        config_alias.write({"payment_method_ids": [(6, 0, [method_alias.id])]})
        config_alias.open_ui()

        method_no_alias = self.env["pos.payment.method"].create({
            "name": "MP alias off", "journal_id": self.journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id,
        })
        config_no_alias = self.env["pos.config"].create({"name": "Caja alias off"})
        config_no_alias.write({"payment_method_ids": [(6, 0, [method_no_alias.id])]})
        config_no_alias.open_ui()

        payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482360", "account_id": self.account.id,
            "amount": 800.0, "date_approved": "2026-08-03 15:22:00",
            "source": "alias", "mp_pos_id": False, "state": "available",
        })
        notified, patched = self._spy_on_notify()
        with patched:
            payment._notify_open_sessions()

        self.assertIn(config_alias.id, notified)
        self.assertNotIn(config_no_alias.id, notified)

    def test_a_method_with_another_terminal_is_not_notified(self):
        """I-6: sólo se avisa a los métodos de este módulo.

        `get_mercadopago_unmatched()` ya filtraba por `use_payment_terminal`;
        el bus no. Un método con `mp_account_id` cargado pero otra terminal
        -o ninguna- recibía avisos de una bandeja que su caja no consulta.
        """
        foreign_method = self.env["pos.payment.method"].create({
            "name": "Efectivo con cuenta MP cargada", "journal_id": self.journal.id,
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
        })
        foreign_config = self.env["pos.config"].create({"name": "Caja otra terminal"})
        foreign_config.write({"payment_method_ids": [(6, 0, [foreign_method.id])]})
        foreign_config.open_ui()

        payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482381", "account_id": self.account.id,
            "amount": 1500.0, "date_approved": "2026-08-03 15:26:00",
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })
        notified, patched = self._spy_on_notify()
        with patched:
            payment._notify_open_sessions()

        self.assertIn(self.config.id, notified)
        self.assertNotIn(foreign_config.id, notified)

    def test_batch_groups_by_account_and_qr_instead_of_per_payment(self):
        """Varios pagos del mismo QR en un lote comparten la búsqueda de métodos.

        No es un conteo exacto de queries SQL (frágil entre entornos): se
        verifica a nivel de llamada a pos.payment.method.search() que el
        camino de lote agrupa por (cuenta, QR) en vez de repetir la
        resolución por cada pago, además de que ambos pagos igual se
        notifican a la caja correcta.
        """
        payment_a = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482371", "account_id": self.account.id,
            "amount": 1500.0, "date_approved": "2026-08-03 15:23:00",
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })
        payment_b = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482372", "account_id": self.account.id,
            "amount": 750.0, "date_approved": "2026-08-03 15:24:00",
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })
        batch = payment_a + payment_b

        notified = []
        original_notify = type(self.env["pos.config"])._notify

        def spy_notify(self_config, name, message, *args, **kwargs):
            notified.append((self_config.id, message.get("mp_payment_id")))
            return original_notify(self_config, name, message, *args, **kwargs)

        PaymentMethodModel = type(self.env["pos.payment.method"])
        original_search = PaymentMethodModel.search
        search_calls = []

        def spy_search(self_model, *args, **kwargs):
            search_calls.append(args)
            return original_search(self_model, *args, **kwargs)

        with patch.object(type(self.env["pos.config"]), "_notify", spy_notify), \
                patch.object(PaymentMethodModel, "search", spy_search):
            batch._notify_open_sessions()

        self.assertEqual(
            len(search_calls), 1,
            "Dos pagos del mismo QR deben resolver los métodos en una sola búsqueda, no una por pago.",
        )
        self.assertEqual(
            {mp_id for (_config_id, mp_id) in notified},
            {"170951482371", "170951482372"},
        )
        self.assertTrue(all(config_id == self.config.id for config_id, _mp_id in notified))
