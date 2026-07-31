# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviProblemClients(CviCommon):
    """E8 sobre el cliente propio: marca (HU-27), alerta (HU-28), historial (HU-29)."""

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 0

    def _card(self, customer=None, date_sale="2020-01-15", confirm=True):
        card = self.env["cvi.card"].create({
            "customer_id": (customer or self.customer).id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": date_sale,
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        if confirm:
            card.action_confirm()
        return card

    # --- identidad por DNI ---

    def test_dni_is_stored_without_dots_or_spaces(self):
        """30.111.222 y 30111222 son la misma persona: el formato no puede duplicarla."""
        customer = self.env["cvi.customer"].create({
            "name": "Con puntos", "dni": "30.111.222",
        })
        self.assertEqual(customer.dni, "30111222")

    def test_the_same_dni_cannot_be_loaded_twice(self):
        self.env["cvi.customer"].create({"name": "Primero", "dni": "40111222"})
        with self.assertRaises(Exception):
            self.env["cvi.customer"].create({"name": "Segundo", "dni": "40.111.222"})
            self.env.flush_all()

    def test_lookup_finds_the_customer_whatever_the_format(self):
        customer = self.env["cvi.customer"].create({
            "name": "Buscado", "dni": "50111222",
        })
        found = self.env["cvi.customer"]._cvi_find_by_dni("50.111.222")
        self.assertEqual(found, customer)

    def test_lookup_returns_empty_when_there_is_no_match(self):
        self.assertFalse(self.env["cvi.customer"]._cvi_find_by_dni("99999999"))

    # --- marcar (HU-27) ---

    def test_marking_requires_a_reason(self):
        with self.assertRaises(UserError):
            self.customer.action_mark_problematic()

    def test_marking_records_who_and_when(self):
        self.customer.problematic_reason = "Nunca pagó y se mudó."
        self.customer.action_mark_problematic()
        self.assertTrue(self.customer.problematic)
        self.assertEqual(self.customer.problematic_user_id, self.env.user)
        self.assertTrue(self.customer.problematic_date)

    def test_mark_can_be_lifted(self):
        self.customer.problematic_reason = "Nunca pagó."
        self.customer.action_mark_problematic()
        self.customer.action_unmark_problematic()
        self.assertFalse(self.customer.problematic)

    def test_recovered_card_suggests_the_mark_without_applying_it(self):
        """Se sugiere, no se marca solo: la decisión es del administrador (HU-27)."""
        card = self._card()
        card.to_recover_reason = "Sin pagar."
        card.action_mark_to_recover()
        card.action_register_recovery()
        self.customer.invalidate_recordset()
        self.assertTrue(self.customer.suggest_problematic)
        self.assertFalse(self.customer.problematic)

    def test_overdue_card_suggests_the_mark(self):
        self._card()
        self.customer.invalidate_recordset()
        self.assertTrue(self.customer.suggest_problematic)

    def test_a_clean_client_is_not_suggested(self):
        clean = self.env["cvi.customer"].create({"name": "Sano", "dni": "60111222"})
        self.assertFalse(clean.suggest_problematic)

    # --- alerta al vender (HU-28) ---

    def test_no_alert_for_a_client_without_history(self):
        clean = self.env["cvi.customer"].create({"name": "Nuevo", "dni": "70111222"})
        card = self._card(customer=clean, confirm=False)
        self.assertFalse(card.has_partner_alert)

    def test_alert_when_the_client_is_flagged(self):
        self.customer.problematic_reason = "Nunca pagó."
        self.customer.action_mark_problematic()
        card = self._card(confirm=False)
        self.assertTrue(card.has_partner_alert)
        self.assertIn("problemático", card.partner_alert)

    def test_alert_mentions_a_previous_recovery(self):
        previous = self._card()
        previous.to_recover_reason = "Sin pagar."
        previous.action_mark_to_recover()
        previous.action_register_recovery()
        card = self._card(confirm=False)
        self.assertTrue(card.has_partner_alert)
        self.assertIn(previous.name, card.partner_alert)

    def test_alert_mentions_the_previous_vendor(self):
        """HU-28 quiere saber que el problema fue con otro vendedor."""
        previous = self._card()
        card = self._card(confirm=False)
        self.assertIn(self.vendor_user.name, card.partner_alert)
        self.assertIn(previous.name, card.partner_alert)

    def test_alert_does_not_block_the_sale(self):
        """Decisión del cliente: la alerta solo advierte (punto abierto 8 del spec)."""
        self.customer.problematic_reason = "Nunca pagó."
        self.customer.action_mark_problematic()
        card = self._card(confirm=False)
        self.assertTrue(card.has_partner_alert)
        card.action_confirm()
        self.assertEqual(card.state, "sold")

    # --- historial (HU-29) ---

    def test_history_lists_previous_cards(self):
        previous = self._card()
        card = self._card(confirm=False)
        self.assertIn(previous, card.partner_history_ids)

    def test_history_excludes_the_card_itself(self):
        card = self._card()
        self.assertNotIn(card, card.partner_history_ids)

    def test_history_ignores_drafts(self):
        draft = self._card(confirm=False)
        card = self._card(confirm=False)
        self.assertNotIn(draft, card.partner_history_ids)

    def test_customer_counters(self):
        self._card()
        recovered = self._card()
        recovered.to_recover_reason = "Sin pagar."
        recovered.action_mark_to_recover()
        recovered.action_register_recovery()
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.card_count, 2)
        self.assertEqual(self.customer.recovered_count, 1)


@tagged("post_install", "-at_install")
class TestCviSaleStartWizard(CviCommon):
    """El circuito de venta arranca por DNI (HU-28)."""

    def _wizard(self, dni):
        return self.env["cvi.sale.start.wizard"].create({"dni": dni})

    def test_search_finds_an_existing_customer(self):
        wizard = self._wizard("20.111.111")
        wizard.action_search()
        self.assertTrue(wizard.found)
        self.assertEqual(wizard.customer_id, self.customer)
        self.assertEqual(wizard.name, self.customer.name)

    def test_search_of_an_unknown_dni_offers_to_create(self):
        wizard = self._wizard("88888888")
        wizard.action_search()
        self.assertTrue(wizard.searched)
        self.assertFalse(wizard.found)
        self.assertFalse(wizard.customer_id)

    def test_search_shows_the_antecedents_before_the_sale_starts(self):
        """Es el punto del asistente: el aviso aparece antes de cargar un solo mueble."""
        self.customer.problematic_reason = "Nunca pagó."
        self.customer.action_mark_problematic()
        wizard = self._wizard("20111111")
        wizard.action_search()
        self.assertTrue(wizard.has_alert)
        self.assertIn("problemático", wizard.alert)

    def test_starting_a_sale_with_an_existing_customer(self):
        wizard = self._wizard("20111111")
        wizard.action_search()
        action = wizard.action_start_sale()
        card = self.env["cvi.card"].browse(action["res_id"])
        self.assertEqual(card.customer_id, self.customer)
        self.assertEqual(card.vendor_id, self.env.user)

    def test_starting_a_sale_creates_the_customer_when_the_dni_is_new(self):
        wizard = self._wizard("77.777.777")
        wizard.action_search()
        wizard.name = "Cliente Nuevo Test"
        wizard.street = "Los Álamos 100"
        action = wizard.action_start_sale()
        card = self.env["cvi.card"].browse(action["res_id"])
        self.assertEqual(card.customer_id.dni, "77777777")
        self.assertEqual(card.customer_id.street, "Los Álamos 100")

    def test_a_new_customer_needs_a_name(self):
        wizard = self._wizard("66666666")
        wizard.action_search()
        with self.assertRaises(UserError):
            wizard.action_start_sale()

    def test_cannot_start_without_searching_first(self):
        with self.assertRaises(UserError):
            self._wizard("20111111").action_start_sale()
