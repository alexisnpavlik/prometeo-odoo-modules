from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReservaAImputacion(TransactionCase):
    """Cierre de la reserva por uuid (Task 11) al crearse el pos.payment real."""

    def setUp(self):
        """Arma cuenta, método y una reserva ya hecha, en una compañía activa.

        En `calidad` la compañía id 1 está archivada: crear todo explícitamente
        en una compañía activa evita romper contra la regla multiempresa, igual
        que en test_reserva_por_uuid.py.
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
            "name": "Caja test cierre reserva", "company_id": self.company.id,
        })
        self.config.write({"payment_method_ids": [(4, self.method.id)]})
        self.config.open_ui()
        self.session = self.config.current_session_id
        self.payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351", "account_id": self.account.id,
            "amount": 1500.0, "date_approved": fields.Datetime.now(),
            "source": "qr", "mp_pos_id": "64365871", "state": "available",
        })

    def _order(self):
        """Crea una orden vacía sobre la sesión abierta de la caja de prueba."""
        return self.env["pos.order"].create({
            "session_id": self.session.id, "amount_total": 1500.0, "amount_tax": 0,
            "amount_paid": 0, "amount_return": 0,
        })

    def test_reserved_payment_links_on_line_creation(self):
        """Al crearse el pos.payment con ese uuid, la reserva se convierte en imputación."""
        self.payment.reserve_for_uuid("uuid-abc")
        self.assertEqual(self.payment.state, "matched")
        self.assertFalse(self.payment.pos_payment_id)

        line = self.env["pos.payment"].create({
            "pos_order_id": self._order().id,
            "payment_method_id": self.method.id,
            "amount": 1500.0,
            "mercadopago_uuid": "uuid-abc",
        })

        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.pos_payment_id, line)
        self.assertEqual(self.payment.pos_session_id, self.session)
        self.assertEqual(self.payment.amount_difference, 0.0)
        self.assertEqual(line.mercadopago_payment_id, self.payment)

    def test_line_without_reservation_is_untouched(self):
        """Una línea sin uuid reservado no toca la bandeja."""
        line = self.env["pos.payment"].create({
            "pos_order_id": self._order().id,
            "payment_method_id": self.method.id,
            "amount": 1500.0,
        })
        self.assertFalse(line.mercadopago_payment_id)
        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.state, "available")

    def test_line_with_uuid_but_no_reservation_does_not_break_the_sale(self):
        """Un uuid sin reserva asociada se loguea y no rompe la creación de la venta."""
        line = self.env["pos.payment"].create({
            "pos_order_id": self._order().id,
            "payment_method_id": self.method.id,
            "amount": 1500.0,
            "mercadopago_uuid": "uuid-que-no-existe",
        })
        self.assertTrue(line.id)
        self.assertFalse(line.mercadopago_payment_id)

    def test_a_revert_landing_between_the_search_and_the_write_does_not_link(self):
        """I-7: el cierre de la reserva re-verifica el estado con la fila tomada.

        `pos.payment.create()` escribía `pos_payment_id` sin `FOR UPDATE` ni
        re-chequeo, a diferencia de `impute()`. Si un revert concurrente ganaba
        entre el `search` y el `write`, el pago quedaba en `available` **con**
        `pos_payment_id`: reaparecía en la bandeja de la caja y además contaba
        como cobrado en esa venta.

        La carrera se reproduce en una sola transacción haciendo que el `search`
        devuelva la reserva que el revert ya deshizo -exactamente lo que ve el
        código cuando la otra transacción commitea en el medio-.
        """
        self.payment.reserve_for_uuid("uuid-abc")
        self.payment.revert(reason="revert concurrente desde el backoffice")
        self.assertEqual(self.payment.state, "available")

        Inbox = type(self.env["mercadopago.payment"])
        original_search = Inbox.search
        stale = self.payment

        def stale_search(model, domain, *args, **kwargs):
            result = original_search(model, domain, *args, **kwargs)
            reserva = any(
                isinstance(leaf, (list, tuple)) and leaf[0] == "pos_payment_uuid"
                for leaf in domain
            )
            if reserva and not result:
                return model.browse(stale.id)
            return result

        with patch.object(Inbox, "search", stale_search):
            line = self.env["pos.payment"].create({
                "pos_order_id": self._order().id,
                "payment_method_id": self.method.id,
                "amount": 1500.0,
                "mercadopago_uuid": "uuid-abc",
            })

        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.state, "available")
        self.assertFalse(
            self.payment.pos_payment_id,
            "El pago quedó disponible y cobrado a la vez: reaparece en la bandeja "
            "y además cuenta en la venta.",
        )
        self.assertFalse(line.mercadopago_payment_id)

    def test_load_pos_data_fields_exposes_the_uuid(self):
        """El POS necesita sincronizar mercadopago_uuid para cerrar la reserva.

        Pero sin recortar la lista: `pos.payment` no override el método en el
        core, así que el mixin devuelve `[]`, que el cargador interpreta como
        "todos los campos". Convertir ese `[]` en una lista de un solo elemento
        dejaba al modelo del navegador sin `pos_order_id` y rompía el cobro con
        cualquier método de pago.
        """
        fields_list = self.env["pos.payment"]._load_pos_data_fields(self.config.id)
        if fields_list:
            self.assertIn("mercadopago_uuid", fields_list)
            self.assertIn(
                "pos_order_id", fields_list,
                "La lista no puede recortar los campos que el POS necesita",
            )
        else:
            self.assertEqual(
                fields_list, [],
                "Con lista vacía el cargador trae todos los campos, uuid incluido",
            )

    def test_payment_line_keeps_its_order_link_for_the_browser(self):
        """El campo del que depende set_amount() en el navegador sigue disponible.

        Guard de regresión del bug que rompía `add_paymentline`: si la lista de
        campos deja de incluir `pos_order_id`, `this.pos_order_id` es undefined
        en el cliente y `assert_editable()` revienta.
        """
        fields_list = self.env["pos.payment"]._load_pos_data_fields(self.config.id)
        model_fields = self.env["pos.payment"]._fields
        effective = fields_list or list(model_fields)
        for needed in ("pos_order_id", "payment_method_id", "amount"):
            self.assertIn(needed, effective)

    def test_reservation_from_another_cash_register_does_not_get_linked(self):
        """El uuid lo elige el navegador: una línea de otra caja no se lo queda.

        Misma cuenta, distinto QR. Sin el filtro de canal en el `create()`,
        una línea de la caja B que declarara el uuid de una reserva viva de
        la caja A se quedaría con ese pago -y ahí no hay vuelta atrás, es la
        operación que deja el pago imputado a una venta-.
        """
        self.payment.reserve_for_uuid("uuid-abc")

        other_method = self.env["pos.payment.method"].with_company(self.company).create({
            "name": "MP QR caja B", "journal_id": self.method.journal_id.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "99999999",
            "company_id": self.company.id,
        })
        other_config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja B", "company_id": self.company.id,
        })
        other_config.write({"payment_method_ids": [(4, other_method.id)]})
        other_config.open_ui()
        other_order = self.env["pos.order"].create({
            "session_id": other_config.current_session_id.id, "amount_total": 1500.0,
            "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
        })

        line = self.env["pos.payment"].create({
            "pos_order_id": other_order.id,
            "payment_method_id": other_method.id,
            "amount": 1500.0,
            "mercadopago_uuid": "uuid-abc",
        })

        self.assertFalse(line.mercadopago_payment_id)
        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.state, "matched")
        self.assertFalse(self.payment.pos_payment_id)
