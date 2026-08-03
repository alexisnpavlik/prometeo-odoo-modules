# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviPaymentWizard(CviCommon):
    """Cobro con monto editable: el cliente paga lo que puede, no lo que dice la cuota."""

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 3650
        self.card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_12.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    def _collection_installments(self):
        return self.card.installment_ids.filtered(
            lambda i: not i.is_commission
        ).sorted(lambda i: (i.date_due, i.sequence))

    def _wizard_from(self, installment):
        action = installment.action_register_payment()
        return self.env["cvi.payment.wizard"].with_context(
            **action["context"]
        ).create({})

    # --- lo que trae cargado ---

    def test_the_amount_comes_loaded_with_the_installment(self):
        """El default es la cuota entera: el caso normal se resuelve sin escribir nada."""
        first = self._collection_installments()[0]
        wizard = self._wizard_from(first)
        self.assertEqual(wizard.amount, first.amount_residual)
        self.assertEqual(wizard.installment_id, first)

    def test_a_partially_paid_installment_offers_only_what_is_left(self):
        first = self._collection_installments()[0]
        wizard = self._wizard_from(first)
        wizard.amount = 4000.0
        wizard.action_confirm_payment()
        self.assertEqual(self._wizard_from(first).amount, 6000.0)

    def test_the_wizard_shows_what_the_client_drags_from_before(self):
        """Sin ver lo atrasado, el cobrador no puede decidir cuánto pedir."""
        installments = self._collection_installments()
        wizard = self._wizard_from(installments[0])
        wizard.amount = 4000.0
        wizard.action_confirm_payment()
        second = self._wizard_from(installments[1])
        self.assertEqual(second.amount_due_before, 6000.0)
        self.assertEqual(second.amount_installment, 10000.0)

    def test_nothing_dragged_when_the_previous_installments_are_settled(self):
        installments = self._collection_installments()
        self._wizard_from(installments[0]).action_confirm_payment()
        self.assertEqual(self._wizard_from(installments[1]).amount_due_before, 0.0)

    def test_an_untouched_previous_installment_also_counts(self):
        """No hace falta que esté vencida: la imputación es FIFO igual.

        Si el cobrador abre la cuota 2 con la 1 sin pagar, lo que cobre va a la 1.
        Mostrarlo evita que crea que cobró la cuota que tiene en pantalla.
        """
        wizard = self._wizard_from(self._collection_installments()[1])
        self.assertEqual(wizard.amount_due_before, 10000.0)

    def test_charge_everything_due_adds_up_the_arrears(self):
        installments = self._collection_installments()
        wizard = self._wizard_from(installments[0])
        wizard.amount = 4000.0
        wizard.action_confirm_payment()
        second = self._wizard_from(installments[1])
        second.action_charge_everything_due()
        self.assertEqual(second.amount, 16000.0)

    # --- lo que registra ---

    def test_a_partial_payment_leaves_the_installment_open(self):
        first = self._collection_installments()[0]
        wizard = self._wizard_from(first)
        wizard.amount = 4000.0
        wizard.action_confirm_payment()
        self.assertEqual(first.amount_paid, 4000.0)
        self.assertEqual(first.amount_residual, 6000.0)
        self.assertEqual(first.state, "partial")

    def test_paying_more_covers_the_old_debt_first(self):
        """El caso que motivó todo: al mes siguiente paga su cuota más lo que faltó.

        La imputación es FIFO, así que el cobrador no tiene que decir a qué cuota va
        cada peso: alcanza con cargar lo que el cliente entrega.
        """
        installments = self._collection_installments()
        first_wizard = self._wizard_from(installments[0])
        first_wizard.amount = 4000.0
        first_wizard.action_confirm_payment()

        second_wizard = self._wizard_from(installments[1])
        second_wizard.amount = 16000.0
        second_wizard.action_confirm_payment()

        self.assertEqual(installments[0].state, "paid")
        self.assertEqual(installments[1].state, "paid")

    def test_the_payment_records_who_collected_it(self):
        first = self._collection_installments()[0]
        wizard = self._wizard_from(first).with_user(self.collector_user)
        wizard.action_confirm_payment()
        payment = self.card.payment_ids.filtered(lambda p: not p.is_commission)
        self.assertEqual(payment.user_id, self.collector_user)
        self.assertEqual(payment.state, "posted")

    def test_the_note_reaches_the_payment(self):
        wizard = self._wizard_from(self._collection_installments()[0])
        wizard.note = "Pagó en dos billetes."
        wizard.action_confirm_payment()
        payment = self.card.payment_ids.filtered(lambda p: not p.is_commission)
        self.assertEqual(payment.note, "Pagó en dos billetes.")

    def test_the_date_can_differ_from_today(self):
        wizard = self._wizard_from(self._collection_installments()[0])
        wizard.date = "2026-03-05"
        wizard.action_confirm_payment()
        payment = self.card.payment_ids.filtered(lambda p: not p.is_commission)
        self.assertEqual(str(payment.date), "2026-03-05")

    # --- lo que no deja hacer ---

    def test_cannot_collect_more_than_the_card_owes(self):
        """Cobrar de más dejaría plata sin imputar y la rendición no cerraría."""
        wizard = self._wizard_from(self._collection_installments()[0])
        wizard.amount = 999999.0
        with self.assertRaises(UserError):
            wizard.action_confirm_payment()

    def test_an_overpayment_does_not_leave_a_payment_behind(self):
        """Si se rechaza el monto, no puede quedar el cobro a medio registrar."""
        before = len(self.card.payment_ids)
        wizard = self._wizard_from(self._collection_installments()[0])
        wizard.amount = 999999.0
        with self.assertRaises(UserError):
            wizard.action_confirm_payment()
        self.card.invalidate_recordset(["payment_ids"])
        self.assertEqual(len(self.card.payment_ids), before)

    def test_a_paid_installment_cannot_be_collected_again(self):
        first = self._collection_installments()[0]
        self._wizard_from(first).action_confirm_payment()
        with self.assertRaises(UserError):
            first.action_register_payment()

    def test_a_draft_card_takes_no_payments(self):
        draft = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        draft._cvi_generate_installments()
        with self.assertRaises(UserError):
            draft.installment_ids[0].action_register_payment()

    # --- la entrega del vendedor (RN-01) ---

    def test_the_delivery_opens_the_same_wizard_with_its_own_amount(self):
        action = self.card.action_open_first_payment_wizard()
        wizard = self.env["cvi.payment.wizard"].with_context(
            **action["context"]
        ).create({})
        commission = self.card.installment_ids.filtered("is_commission")
        self.assertTrue(wizard.is_commission)
        self.assertEqual(wizard.amount, commission.amount_residual)

    def test_the_delivery_can_be_paid_in_parts(self):
        action = self.card.action_open_first_payment_wizard()
        wizard = self.env["cvi.payment.wizard"].with_context(
            **action["context"]
        ).create({})
        wizard.amount = 3000.0
        wizard.action_confirm_payment()
        commission = self.card.installment_ids.filtered("is_commission")
        self.assertEqual(commission.amount_paid, 3000.0)
        self.assertFalse(self.card.first_installment_paid)

    def test_the_delivery_is_always_credited_to_the_vendor(self):
        """La comisión es del vendedor aunque la registre el administrador (RN-01)."""
        action = self.card.action_open_first_payment_wizard()
        wizard = self.env["cvi.payment.wizard"].with_context(
            **action["context"]
        ).create({})
        wizard.action_confirm_payment()
        commission_payment = self.card.payment_ids.filtered("is_commission")
        self.assertEqual(commission_payment.user_id, self.vendor_user)

    def test_the_delivery_does_not_mix_with_the_collection(self):
        """El total a cobrar del asistente de la entrega no incluye las otras cuotas."""
        action = self.card.action_open_first_payment_wizard()
        wizard = self.env["cvi.payment.wizard"].with_context(
            **action["context"]
        ).create({})
        commission = self.card.installment_ids.filtered("is_commission")
        self.assertEqual(wizard.amount_max, commission.amount_residual)
