# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviRouting(CviCommon):

    def _confirmed_card(self, **kwargs):
        """Tarjeta confirmada (estado Vendida) sin cobrador asignado."""
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        card = self.env["cvi.card"].create(vals)
        card.action_confirm()
        return card

    def test_route_moves_card_to_routed(self):
        """Asignar un cobrador y enrutar deja la tarjeta a la espera de aceptación (HU-10)."""
        card = self._confirmed_card()
        card.collector_id = self.collector_user.id
        card.action_route()
        self.assertEqual(card.state, "routed")

    def test_route_without_collector_is_rejected(self):
        """No se puede enrutar sin elegir a quién."""
        card = self._confirmed_card()
        with self.assertRaises(UserError):
            card.action_route()

    def test_routed_card_is_not_in_active_portfolio(self):
        """Mientras no acepte, la tarjeta no está en la cartera activa del cobrador (RN-02)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_route() if card.state == "sold" else None
        self.assertEqual(card.state, "routed")
        active = self.env["cvi.card"].search([
            ("collector_id", "=", self.collector_user.id), ("state", "=", "active"),
        ])
        self.assertNotIn(card, active)

    def test_accept_moves_card_to_active(self):
        """Aceptar pone la tarjeta en la cartera activa del cobrador (HU-12)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.with_user(self.collector_user).action_accept()
        self.assertEqual(card.state, "active")

    def test_only_the_target_collector_can_accept(self):
        """Otro cobrador no puede aceptar una tarjeta que no le fue enrutada."""
        other = self.env["res.users"].create({
            "name": "Otro Cobrador",
            "login": "cvi_collector_other",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        card = self._confirmed_card(collector_id=self.collector_user.id)
        with self.assertRaises(UserError):
            card.with_user(other).action_accept()

    def test_manager_can_accept_on_behalf_of_collector(self):
        """El administrador puede aceptar por el cobrador (traspasos de oficina)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_accept()
        self.assertEqual(card.state, "active")

    def test_accepting_a_non_routed_card_is_rejected(self):
        """No se puede aceptar una tarjeta que no está enrutada."""
        card = self._confirmed_card()
        with self.assertRaises(UserError):
            card.action_accept()

    def test_reject_returns_card_to_vendor(self):
        """Rechazar devuelve la tarjeta al vendedor y libera el cobrador (HU-13)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_reject("Zona que no recorro")
        self.assertEqual(card.state, "sold")
        self.assertFalse(card.collector_id)

    def test_reject_stores_the_reason(self):
        """El motivo del rechazo queda visible para el vendedor (HU-13)."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_reject("Zona que no recorro")
        self.assertEqual(card.reject_reason, "Zona que no recorro")

    def test_reject_without_reason_is_rejected(self):
        """El motivo es obligatorio al rechazar."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        with self.assertRaises(UserError):
            card.action_reject("")

    def test_rejecting_a_non_routed_card_is_rejected(self):
        """Solo se rechaza una tarjeta enrutada."""
        card = self._confirmed_card()
        with self.assertRaises(UserError):
            card.action_reject("No corresponde")

    def test_reject_wizard_rejects_all_selected_cards(self):
        """El wizard de rechazo aplica el mismo motivo a todas las tarjetas elegidas."""
        cards = self._confirmed_card(collector_id=self.collector_user.id)
        cards |= self._confirmed_card(collector_id=self.collector_user.id)
        wizard = self.env["cvi.reject.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "reason": "Ruta discontinuada",
        })
        wizard.action_confirm_reject()
        self.assertEqual(set(cards.mapped("state")), {"sold"})
        self.assertEqual(set(cards.mapped("reject_reason")), {"Ruta discontinuada"})

    def test_rerouting_after_reject_clears_the_reason(self):
        """Al volver a enrutar, el motivo del rechazo anterior se limpia."""
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.action_reject("Zona que no recorro")
        card.collector_id = self.collector_user.id
        card.action_route()
        self.assertFalse(card.reject_reason)
