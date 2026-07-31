# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviProblemClients(CviCommon):
    """E8: clientes problemáticos (HU-27), alerta al vender (HU-28), historial (HU-29)."""

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 0
        self.partner.cvi_dni = "30111222"

    def _card(self, partner=None, date_sale="2020-01-15", confirm=True):
        card = self.env["cvi.card"].create({
            "partner_id": (partner or self.partner).id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": date_sale,
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        if confirm:
            card.action_confirm()
        return card

    # --- marcar (HU-27) ---

    def test_marking_requires_a_reason(self):
        with self.assertRaises(UserError):
            self.partner.action_mark_problematic()

    def test_marking_records_who_and_when(self):
        self.partner.cvi_problematic_reason = "Nunca pagó y se mudó."
        self.partner.action_mark_problematic()
        self.assertTrue(self.partner.cvi_problematic)
        self.assertEqual(self.partner.cvi_problematic_user_id, self.env.user)
        self.assertTrue(self.partner.cvi_problematic_date)

    def test_mark_can_be_lifted(self):
        self.partner.cvi_problematic_reason = "Nunca pagó."
        self.partner.action_mark_problematic()
        self.partner.action_unmark_problematic()
        self.assertFalse(self.partner.cvi_problematic)

    def test_recovered_card_suggests_the_mark_without_applying_it(self):
        """Se sugiere, no se marca solo: la decisión es del administrador (HU-27)."""
        card = self._card()
        card.to_recover_reason = "Sin pagar."
        card.action_mark_to_recover()
        card.action_register_recovery()
        self.partner.invalidate_recordset()
        self.assertTrue(self.partner.cvi_suggest_problematic)
        self.assertFalse(self.partner.cvi_problematic)

    def test_overdue_card_suggests_the_mark(self):
        self._card()
        self.partner.invalidate_recordset()
        self.assertTrue(self.partner.cvi_suggest_problematic)

    def test_a_clean_client_is_not_suggested(self):
        clean = self.env["res.partner"].create({"name": "Cliente Sano"})
        self.assertFalse(clean.cvi_suggest_problematic)

    # --- alerta al vender (HU-28) ---

    def test_no_alert_for_a_client_without_history(self):
        clean = self.env["res.partner"].create({"name": "Cliente Nuevo"})
        card = self._card(partner=clean, confirm=False)
        self.assertFalse(card.has_partner_alert)

    def test_alert_when_the_client_is_flagged(self):
        self.partner.cvi_problematic_reason = "Nunca pagó."
        self.partner.action_mark_problematic()
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

    def test_alert_finds_the_client_under_a_different_name(self):
        """El mismo DNI con otro nombre tiene que disparar la alerta igual (HU-28).

        Es el caso que la historia quiere cubrir: sin esto, cargar al cliente de nuevo
        escribiendo el nombre distinto alcanza para borrarle los antecedentes.
        """
        twin = self.env["res.partner"].create({
            "name": "J. Perez", "cvi_dni": self.partner.cvi_dni,
        })
        self.partner.cvi_problematic_reason = "Nunca pagó."
        self.partner.action_mark_problematic()
        card = self._card(partner=twin, confirm=False)
        self.assertTrue(card.has_partner_alert)

    def test_a_different_dni_does_not_trigger_the_alert(self):
        other = self.env["res.partner"].create({
            "name": "Homónimo", "cvi_dni": "99999999",
        })
        self.partner.cvi_problematic_reason = "Nunca pagó."
        self.partner.action_mark_problematic()
        card = self._card(partner=other, confirm=False)
        self.assertFalse(card.has_partner_alert)

    def test_alert_does_not_block_the_sale(self):
        """Decisión del cliente: la alerta solo advierte (punto abierto 8 del spec)."""
        self.partner.cvi_problematic_reason = "Nunca pagó."
        self.partner.action_mark_problematic()
        card = self._card(confirm=False)
        self.assertTrue(card.has_partner_alert)
        card.action_confirm()
        self.assertEqual(card.state, "sold")

    # --- historial (HU-29) ---

    def test_history_lists_previous_cards_with_their_state(self):
        previous = self._card()
        card = self._card(confirm=False)
        self.assertIn(previous, card.partner_history_ids)

    def test_history_excludes_the_card_itself(self):
        card = self._card()
        self.assertNotIn(card, card.partner_history_ids)

    def test_history_ignores_drafts_and_cancelled(self):
        draft = self._card(confirm=False)
        card = self._card(confirm=False)
        self.assertNotIn(draft, card.partner_history_ids)

    def test_history_spans_the_same_dni(self):
        twin = self.env["res.partner"].create({
            "name": "J. Perez", "cvi_dni": self.partner.cvi_dni,
        })
        previous = self._card()
        card = self._card(partner=twin, confirm=False)
        self.assertIn(previous, card.partner_history_ids)

    def test_partner_history_counters(self):
        self._card()
        recovered = self._card()
        recovered.to_recover_reason = "Sin pagar."
        recovered.action_mark_to_recover()
        recovered.action_register_recovery()
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.cvi_card_count, 2)
        self.assertEqual(self.partner.cvi_recovered_count, 1)
