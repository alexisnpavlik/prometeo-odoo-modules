from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class BackofficeCommon(TransactionCase):
    """Escenario de backoffice: cuenta, caja y bandeja en una compañía activa."""

    def setUp(self):
        """Todo en una compañía activa y explícita.

        En `calidad` la compañía id 1 está archivada: los usuarios de prueba no
        pueden leer nada creado con ella y las pruebas morirían por la regla
        multiempresa antes de llegar a lo que quieren probar.
        """
        super().setUp()
        self.company = self.env["res.company"].search([], limit=1)
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=self.company.ids))
        self.account = self.env["mercadopago.account"].with_company(self.company).create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
            "company_id": self.company.id,
        })
        self.journal = self.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", self.company.id),
        ], limit=1)
        self.method = self.env["pos.payment.method"].with_company(self.company).create({
            "name": "MP QR", "journal_id": self.journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
            "company_id": self.company.id,
        })
        self.config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja backoffice", "company_id": self.company.id,
        })
        self.config.write({"payment_method_ids": [(6, 0, [self.method.id])]})

    def _payment(self, mp_id="170951482351", amount=1500.0, payer_id=False,
                 account=None, state="available"):
        """Un pago de la bandeja, por omisión disponible en la caja de prueba."""
        return self.env["mercadopago.payment"].create({
            "mp_payment_id": mp_id,
            "account_id": (account or self.account).id,
            "amount": amount,
            "date_approved": fields.Datetime.now(),
            "source": "qr", "mp_pos_id": "64365871",
            "mp_payer_id": payer_id, "state": state,
        })

    def _open_order_line(self, amount=1500.0):
        """Abre la caja y devuelve una línea de cobro real."""
        self.config.open_ui()
        order = self.env["pos.order"].create({
            "session_id": self.config.current_session_id.id, "amount_total": amount,
            "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
        })
        return self.env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": self.method.id, "amount": amount,
        })

    def _user(self, login, groups):
        """Un usuario real en la compañía activa, con los grupos pedidos."""
        return self.env["res.users"].create({
            "name": login, "login": login,
            "company_id": self.company.id,
            "company_ids": [(6, 0, self.company.ids)],
            "groups_id": [(6, 0, [self.env.ref(g).id for g in groups])],
        })


@tagged("post_install", "-at_install")
class TestMapeoDePagadores(BackofficeCommon):
    """F-1: el mapeo manual de `mp_payer_id` a cliente, del canal INTER_PSP."""

    def test_partner_can_be_assigned_from_the_backoffice(self):
        """`partner_id` tiene que ser escribible: es todo el mecanismo del mapeo.

        Con el campo `readonly=True` no había forma de crear el primer mapeo, y
        `_resolve_partner()` -que sabe leerlo- nunca encontraba ninguno.
        """
        partner = self.env["res.partner"].create({"name": "Cliente recurrente"})
        payment = self._payment(payer_id="2429168801")
        payment.partner_id = partner
        self.assertEqual(payment.partner_id, partner)
        self.assertEqual(payment.display_payer, "Cliente recurrente")

    def test_assignment_propagates_to_past_payments_of_the_same_payer(self):
        """Spec §9: al mapear un payer id, sus pagos pasados quedan asociados."""
        partner = self.env["res.partner"].create({"name": "Cliente recurrente"})
        old_a = self._payment("111", payer_id="2429168801")
        old_b = self._payment("222", payer_id="2429168801")
        other_payer = self._payment("333", payer_id="9999999")

        self._payment("444", payer_id="2429168801").partner_id = partner

        self.assertEqual(old_a.partner_id, partner)
        self.assertEqual(old_b.partner_id, partner)
        self.assertFalse(other_payer.partner_id)

    def test_propagation_never_overwrites_a_different_partner(self):
        """Un cliente ya resuelto -por CUIT o a mano- es más específico: se respeta."""
        by_vat = self.env["res.partner"].create({"name": "Resuelto por CUIT"})
        mapped = self.env["res.partner"].create({"name": "Mapeado a mano"})
        already = self._payment("111", payer_id="2429168801")
        already.partner_id = by_vat
        pending = self._payment("222", payer_id="2429168801")

        self._payment("333", payer_id="2429168801").partner_id = mapped

        self.assertEqual(already.partner_id, by_vat)
        self.assertEqual(pending.partner_id, mapped)

    def test_future_payments_of_a_mapped_payer_resolve_on_ingest(self):
        """La otra mitad de "pasados y futuros": la ingesta lee el mapeo."""
        partner = self.env["res.partner"].create({"name": "Cliente recurrente"})
        self._payment("111", payer_id="2429168801").partner_id = partner

        resolved = self.env["mercadopago.payment"]._resolve_partner({
            "mp_payer_id": "2429168801",
        })
        self.assertEqual(resolved, partner)

    def test_the_action_offers_the_form_view(self):
        """Spec §9 pide "lista y formulario": sin form no hay dónde mapear."""
        action = self.env.ref("pos_mercadopago_validator.action_mercadopago_payment")
        self.assertIn("form", action.view_mode)
        self.assertTrue(self.env.ref("pos_mercadopago_validator.view_mercadopago_payment_form"))


@tagged("post_install", "-at_install")
class TestReversionBackoffice(BackofficeCommon):
    """F-2: la reversión de §7.4, ahora alcanzable desde la interfaz."""

    def test_revert_needs_a_reason(self):
        """Sin motivo no hay reversión: es lo que queda auditado."""
        line = self._open_order_line()
        payment = self._payment()
        payment.impute(line)
        with self.assertRaises(UserError):
            payment.action_revert_from_backoffice()
        self.assertEqual(payment.state, "matched")

    def test_revert_from_backoffice_frees_the_payment_and_audits(self):
        """Revierte, devuelve el pago a la bandeja y deja el motivo en el pedido."""
        line = self._open_order_line()
        payment = self._payment()
        payment.impute(line)
        order = line.pos_order_id

        payment.backoffice_reason = "Cobro asignado a la venta equivocada"
        payment.action_revert_from_backoffice()

        self.assertEqual(payment.state, "available")
        self.assertFalse(payment.pos_payment_id)
        self.assertFalse(line.mercadopago_payment_id)
        self.assertTrue(any(
            "Cobro asignado a la venta equivocada" in (m.body or "")
            for m in order.message_ids
        ))

    def test_an_orphan_reservation_has_a_way_out(self):
        """La reserva colgada -el navegador se cayó- deja de ser un estado sin salida.

        Queda en `matched` sin `pos_payment_id`: invisible para todas las cajas,
        porque la bandeja del POS sólo muestra `available`. Antes de F-2 no había
        ninguna interfaz que llamara a `revert()`.
        """
        payment = self._payment()
        payment.reserve_for_uuid("uuid-huerfano")
        self.assertEqual(payment.state, "matched")
        self.assertFalse(payment.pos_payment_id)

        payment.backoffice_reason = "El navegador se cayó durante el cobro"
        payment.action_revert_from_backoffice()

        self.assertEqual(payment.state, "available")
        self.assertFalse(payment.pos_payment_uuid)
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 1)

    def test_only_the_manager_group_can_revert(self):
        """La reversión es de backoffice: un cajero no la ejecuta."""
        line = self._open_order_line()
        payment = self._payment()
        payment.impute(line)
        payment.backoffice_reason = "Motivo cualquiera"

        cashier = self._user("cajero_revert_mp", [
            "base.group_user", "point_of_sale.group_pos_user",
        ])
        with self.assertRaises(UserError):
            payment.with_user(cashier).action_revert_from_backoffice()


@tagged("post_install", "-at_install")
class TestDescarte(BackofficeCommon):
    """I-8: `discarded` deja de ser un estado declarado sin camino de entrada."""

    def test_discard_takes_the_payment_out_of_the_inbox(self):
        """Un huérfano descartado deja de ofrecerse a las cajas."""
        payment = self._payment()
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 1)

        payment.backoffice_reason = "Transferencia del dueño, no es una venta"
        payment.action_discard()

        self.assertEqual(payment.state, "discarded")
        self.assertEqual(self.method.get_mp_inbox(1500.0)["matching"], [])

    def test_discard_needs_a_reason_and_an_available_payment(self):
        """Sin motivo no se descarta, y un pago imputado tampoco."""
        payment = self._payment()
        with self.assertRaises(UserError):
            payment.action_discard()

        line = self._open_order_line()
        imputed = self._payment("222")
        imputed.impute(line)
        imputed.backoffice_reason = "Motivo"
        with self.assertRaises(UserError):
            imputed.action_discard()

    def test_a_discarded_payment_can_come_back(self):
        """El descarte no borra: se repone si fue un error."""
        payment = self._payment()
        payment.backoffice_reason = "Descartado por error"
        payment.action_discard()

        payment.action_restore()
        self.assertEqual(payment.state, "available")
        self.assertEqual(len(self.method.get_mp_inbox(1500.0)["matching"]), 1)

    def test_only_the_manager_group_can_discard(self):
        """Descartar un cobro es sacar dinero real del control: no es del cajero."""
        payment = self._payment()
        payment.backoffice_reason = "Motivo"
        cashier = self._user("cajero_descarte_mp", [
            "base.group_user", "point_of_sale.group_pos_user",
        ])
        with self.assertRaises(UserError):
            payment.with_user(cashier).action_discard()


@tagged("post_install", "-at_install")
class TestVisibilidadDeLaBandeja(BackofficeCommon):
    """R-3: la `ir.rule` que acota lo que un cajero ve de la bandeja."""

    def _foreign_account_payment(self):
        """Un pago de una cuenta que no usa ninguna caja de este usuario."""
        foreign = self.env["mercadopago.account"].with_company(self.company).create({
            "name": "Cuenta ajena", "mode": "production", "mp_user_id": "999999999",
            "company_id": self.company.id,
        })
        return self._payment("999", account=foreign)

    def test_cashier_only_reads_payments_of_the_accounts_of_his_registers(self):
        """Un `search_read` directo del cajero no alcanza la bandeja ajena.

        No puede imputar nada ajeno -eso lo cierra `_find_inbox_line()`- pero
        sin regla de registro leía los movimientos de dinero de todas las cajas
        y todas las cuentas.
        """
        own = self._payment()
        foreign = self._foreign_account_payment()

        cashier = self._user("cajero_bandeja_mp", [
            "base.group_user", "point_of_sale.group_pos_user",
        ])
        visible = self.env["mercadopago.payment"].with_user(cashier).search([])

        self.assertIn(own, visible)
        self.assertNotIn(foreign, visible)

    def test_the_manager_group_still_sees_everything(self):
        """El control interno se hace sobre la bandeja completa, no sobre un recorte."""
        own = self._payment()
        foreign = self._foreign_account_payment()

        manager = self._user("gerente_bandeja_mp", [
            "base.group_user", "pos_mercadopago_validator.group_mercadopago_manager",
        ])
        visible = self.env["mercadopago.payment"].with_user(manager).search([])

        self.assertIn(own, visible)
        self.assertIn(foreign, visible)

    def test_the_pos_dialog_still_works_for_the_cashier(self):
        """La regla no puede romper la bandeja del POS, que corre en sudo."""
        self._payment()
        cashier = self._user("cajero_dialogo_mp", [
            "base.group_user", "point_of_sale.group_pos_user",
        ])
        inbox = self.method.with_user(cashier).get_mp_inbox(1500.0)
        self.assertEqual(len(inbox["matching"]), 1)
