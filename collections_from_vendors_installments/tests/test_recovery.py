# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import freeze_time

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviRecovery(CviCommon):
    """E7: mora (HU-23, HU-24) y recupero del mueble (HU-25, HU-26)."""

    def setUp(self):
        super().setUp()
        # Venta vieja y sin tolerancia: las cuotas quedan vencidas de verdad.
        self.company.cvi_overdue_days = 0
        self.card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    # --- mora (HU-23, HU-24) ---

    def test_overdue_amount_sums_the_unpaid_due_installments(self):
        self.assertGreater(self.card.amount_overdue, 0.0)
        self.assertEqual(
            self.card.amount_overdue,
            sum(self.card.installment_ids.filtered(
                lambda i: i.state == "overdue" and not i.is_commission
            ).mapped("amount_residual")),
        )

    def test_days_overdue_counts_from_the_oldest_unpaid(self):
        """La antigüedad es la de la cuota más vieja, que es el criterio de HU-24."""
        overdue = self.card.installment_ids.filtered(
            lambda i: i.state == "overdue" and not i.is_commission
        )
        oldest = min(overdue.mapped("date_due"))
        from odoo import fields as odoo_fields
        expected = (odoo_fields.Date.context_today(self.card) - oldest).days
        self.assertEqual(self.card.days_overdue, expected)

    def test_cron_refreshes_days_overdue_for_open_overdue_installments(self):
        """El cron diario actualiza la antigüedad aunque la cuota ya esté vencida."""
        from odoo import fields as odoo_fields

        days_before_cron = self.card.days_overdue
        tomorrow = odoo_fields.Date.context_today(self.card) + timedelta(days=1)

        with freeze_time("%s 12:00:00" % tomorrow):
            self.env["cvi.installment"]._cron_update_overdue()
            self.card.invalidate_recordset(["days_overdue", "amount_overdue"])
            self.assertEqual(self.card.days_overdue, days_before_cron + 1)

    def test_commission_is_not_counted_as_client_debt(self):
        """La primera cuota es del vendedor: no es deuda del cliente en mora."""
        commission = self.card.installment_ids.filtered("is_commission")
        self.assertTrue(commission)
        self.assertNotIn(commission, self.card.installment_ids.filtered(
            lambda i: i.state == "overdue" and not i.is_commission
        ))

    def test_a_card_up_to_date_has_no_overdue_days(self):
        current = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2099-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        current.action_confirm()
        self.assertEqual(current.days_overdue, 0)
        self.assertEqual(current.amount_overdue, 0.0)

    # --- marcar para retiro (HU-25) ---

    def test_marking_requires_a_reason(self):
        with self.assertRaises(UserError):
            self.card.action_mark_to_recover()

    def test_marking_records_who_and_when(self):
        """Marcar registra motivo, autor y fecha, también por el método directo.

        Antes el motivo se escribía suelto en la ficha con un Form; ahora se pasa
        como argumento y el formulario ya no lo expone.
        """
        self.card.action_mark_to_recover("Cuatro meses sin pagar, no atiende.")
        self.assertTrue(self.card.to_recover)
        self.assertEqual(
            self.card.to_recover_reason, "Cuatro meses sin pagar, no atiende."
        )
        self.assertEqual(self.card.to_recover_user_id, self.env.user)
        self.assertTrue(self.card.to_recover_date)

    def test_marking_does_not_stop_collection(self):
        """Es una marca, no un estado: si el cliente paga, la tarjeta se salva."""
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.assertEqual(self.card.state, "active")

    def test_a_marked_card_can_be_unmarked(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_unmark_to_recover()
        self.assertFalse(self.card.to_recover)

    def test_cannot_mark_a_card_that_is_not_in_collection(self):
        draft = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        draft.to_recover_reason = "Sin pagar."
        with self.assertRaises(UserError):
            draft.action_mark_to_recover()

    def test_cannot_mark_twice(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        with self.assertRaises(UserError):
            self.card.action_mark_to_recover()

    # --- registrar el retiro (HU-26) ---

    def test_the_mark_button_opens_a_dialog_for_the_reason(self):
        """El botón no marca: abre el recuadro donde se escribe el motivo (HU-25).

        Mismo criterio que la marca de mala paga: el motivo dejó de ser un campo
        suelto del formulario, así que se pide en el momento de marcar.
        """
        action = self.card.action_open_recover_wizard()
        self.assertEqual(action["res_model"], "cvi.recover.wizard")
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["context"]["default_card_id"], self.card.id)
        self.assertFalse(self.card.to_recover)

    def test_the_dialog_marks_the_card_with_its_reason(self):
        """Lo escrito en el recuadro queda como motivo, con autor y fecha."""
        wizard = self.env["cvi.recover.wizard"].create({
            "card_id": self.card.id,
            "reason": "Cuatro cuotas sin pagar y se mudó.",
        })
        wizard.action_confirm_recover()
        self.assertTrue(self.card.to_recover)
        self.assertEqual(self.card.to_recover_reason, "Cuatro cuotas sin pagar y se mudó.")
        self.assertEqual(self.card.to_recover_user_id, self.env.user)
        self.assertTrue(self.card.to_recover_date)

    def test_the_dialog_rejects_a_blank_reason(self):
        """Un motivo en blanco no alcanza: el required de la vista no corre en el servidor."""
        wizard = self.env["cvi.recover.wizard"].create({
            "card_id": self.card.id,
            "reason": "   ",
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_recover()
        self.assertFalse(self.card.to_recover)

    def _customer_history(self):
        """Cuerpos del historial del cliente, del mensaje más nuevo al más viejo."""
        return self.env["mail.message"].search(
            [("model", "=", "cvi.customer"), ("res_id", "=", self.customer.id)],
            order="id desc",
        ).mapped("body")

    def test_marking_for_recovery_shows_in_the_customer_history(self):
        """Marcar una tarjeta para retiro queda en el historial del cliente (HU-25).

        En el chatter de la tarjeta ya quedaba, pero quien atiende al cliente abre su
        ficha, no la de cada compra.
        """
        self.card.action_mark_to_recover("Cuatro cuotas sin pagar.")
        history = " ".join(self._customer_history())
        self.assertIn(self.card.name, history)
        self.assertIn("retiro", history.lower())
        self.assertIn("Cuatro cuotas sin pagar.", history)

    def test_lifting_the_recovery_mark_shows_in_the_customer_history(self):
        """Si el cliente se pone al día, el historial también lo dice."""
        self.card.action_mark_to_recover("Sin pagar.")
        self.card.action_unmark_to_recover()
        latest = self._customer_history()[0]
        self.assertIn(self.card.name, latest)
        self.assertIn("levant", latest.lower())

    def test_the_actual_recovery_shows_in_the_customer_history(self):
        """El retiro efectivo también: es el antecedente más fuerte del cliente."""
        self._recover()
        latest = self._customer_history()[0]
        self.assertIn(self.card.name, latest)
        self.assertIn("RETIRADO", latest)

    def _recover(self):
        """Marca y registra el retiro, que es la secuencia obligada."""
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()

    def test_recovery_cancels_what_was_left_to_collect(self):
        """Retirar el mueble cancela las cuotas pendientes (HU-26).

        No se reclaman más: la deuda se dio por perdida junto con el mueble, y
        dejarlas Pendientes hacía que la tarjeta siguiera mostrando saldo vivo.
        """
        self._recover()
        unpaid = self.card.installment_ids.filtered(lambda i: i.amount_paid < i.amount)
        self.assertTrue(unpaid, "la tarjeta tiene que tener cuotas sin cobrar")
        self.assertEqual(set(unpaid.mapped("state")), {"cancelled"})

    def test_recovered_card_shows_no_outstanding_balance(self):
        """El saldo queda en cero: no hay nada más que cobrar."""
        self._recover()
        self.assertEqual(self.card.amount_residual, 0.0)

    def test_an_already_paid_installment_stays_paid(self):
        """Lo que el cliente pagó no se convierte en cancelado."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 10000.0, "date": "2020-03-10",
        })
        payment.action_post()
        collected = self.card.installment_ids.filtered(lambda i: not i.is_commission)[0]
        self.assertEqual(collected.state, "paid")
        self._recover()
        self.assertEqual(collected.state, "paid")
        self.assertEqual(self.card.amount_paid, 10000.0)

    def test_recovered_card_leaves_the_overdue_report(self):
        """Sin cuotas vencidas, la tarjeta retirada sale del listado de morosos."""
        self.assertGreater(self.card.amount_overdue, 0.0)
        self._recover()
        self.assertEqual(self.card.amount_overdue, 0.0)
        self.assertEqual(self.card.days_overdue, 0)

    def test_a_recovered_card_cannot_be_collected_anymore(self):
        """Con las cuotas canceladas no queda dónde imputar un cobro nuevo."""
        self._recover()
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 1000.0, "date": "2020-04-10",
        })
        with self.assertRaises(UserError):
            payment.action_post()

    def test_the_recovered_location_is_flagged_for_its_report(self):
        """La ubicación de recuperados está marcada: es lo que filtra el reporte."""
        location = self.env.ref(
            "collections_from_vendors_installments.stock_location_recovered"
        )
        self.assertTrue(location.cvi_is_recovered_location)

    def test_recovery_needs_the_card_marked_first(self):
        with self.assertRaises(UserError):
            self.card.action_register_recovery()

    def test_recovery_closes_the_card(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        self.assertEqual(self.card.state, "recovered")

    def test_recovery_records_what_had_been_paid(self):
        """Cuánto pagó el cliente hasta el retiro es el dato que después se discute."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 5000.0, "date": "2020-03-10",
        })
        payment.action_post()
        paid_before = self.card.amount_paid
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        self.assertEqual(self.card.amount_paid_at_recovery, paid_before)

    def test_recovered_unit_goes_to_the_recovered_location(self):
        """No vuelve al stock vendible: un mueble usado no es uno nuevo."""
        location = self.env.ref(
            "collections_from_vendors_installments.stock_location_recovered"
        )
        before = self.env["stock.quant"]._get_available_quantity(
            self.product, location
        )
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        after = self.env["stock.quant"]._get_available_quantity(self.product, location)
        self.assertEqual(after, before + self.card.quantity)

    def test_recovery_leaves_a_validated_picking(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        self.assertTrue(self.card.recovery_picking_id)
        self.assertEqual(self.card.recovery_picking_id.state, "done")

    def test_cannot_recover_twice(self):
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        with self.assertRaises(UserError):
            self.card.action_register_recovery()

    def test_recovered_card_is_out_of_the_collection_agenda(self):
        """Una tarjeta retirada deja de generar cobranza (HU-26).

        La agenda filtra card_state == 'active'; al pasar a 'recovered' sale sola.
        """
        self.card.to_recover_reason = "Sin pagar."
        self.card.action_mark_to_recover()
        self.card.action_register_recovery()
        agenda = self.env["cvi.installment"].search([
            ("card_state", "=", "active"),
            ("is_commission", "=", False),
            ("card_id", "=", self.card.id),
        ])
        self.assertFalse(agenda)
