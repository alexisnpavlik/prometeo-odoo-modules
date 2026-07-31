# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviTransfer(CviCommon):

    def setUp(self):
        super().setUp()
        self.collector_dest = self.env["res.users"].create({
            "name": "Cobrador Destino",
            "login": "cvi_collector_dest",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def _active_cards(self, how_many):
        """`how_many` tarjetas en cobranza a cargo de `self.collector_user`."""
        cards = self.env["cvi.card"]
        for _index in range(how_many):
            card = self.env["cvi.card"].create({
                "partner_id": self.partner.id,
                "vendor_id": self.vendor_user.id,
                "product_id": self.product.id,
                "date_sale": "2026-01-15",
                "plan_id": self.plan_3.id,
                "charge_day_month": 10,
                "collector_id": self.collector_user.id,
            })
            card.action_confirm()
            card.action_accept()
            cards |= card
        return cards

    def _wizard(self, cards, reason="Reorganización de rutas"):
        return self.env["cvi.transfer.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_dest_id": self.collector_dest.id,
            "reason": reason,
        })

    def test_transfer_moves_cards_to_destination(self):
        """La tarjeta pasa a la cartera del cobrador destino (HU-30)."""
        cards = self._active_cards(1)
        self._wizard(cards).action_confirm_transfer()
        self.assertEqual(cards.collector_id, self.collector_dest)

    def test_transferred_card_stays_active(self):
        """La tarjeta transferida sigue en cobranza: no vuelve a pendiente de aceptar."""
        cards = self._active_cards(1)
        self._wizard(cards).action_confirm_transfer()
        self.assertEqual(cards.state, "active")

    def test_origin_collector_no_longer_sees_the_card(self):
        """El cobrador de origen deja de tener la tarjeta en su cartera (HU-30)."""
        cards = self._active_cards(1)
        self._wizard(cards).action_confirm_transfer()
        origin_portfolio = self.env["cvi.card"].search([
            ("collector_id", "=", self.collector_user.id), ("state", "=", "active"),
        ])
        self.assertNotIn(cards, origin_portfolio)

    def test_transfer_is_logged_with_reason_and_users(self):
        """Queda registrada la transferencia con origen, destino y motivo (HU-30, RN-08)."""
        cards = self._active_cards(1)
        self._wizard(cards, "Cambio de zona").action_confirm_transfer()
        body = cards.message_ids[0].body
        self.assertIn("Cambio de zona", body)
        self.assertIn(self.collector_user.name, body)
        self.assertIn(self.collector_dest.name, body)

    def test_mass_transfer(self):
        """Se pueden transferir varias tarjetas de una sola vez (HU-30)."""
        cards = self._active_cards(10)
        self._wizard(cards).action_confirm_transfer()
        self.assertEqual(set(cards.mapped("collector_id")), {self.collector_dest})

    def test_reason_is_required(self):
        """No se transfiere sin motivo."""
        cards = self._active_cards(1)
        with self.assertRaises(UserError):
            self._wizard(cards, "   ").action_confirm_transfer()

    def test_transfer_to_same_collector_is_rejected(self):
        """No tiene sentido transferir una tarjeta al cobrador que ya la tiene."""
        cards = self._active_cards(1)
        wizard = self.env["cvi.transfer.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_dest_id": self.collector_user.id,
            "reason": "Sin cambio",
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_transfer()

    def test_draft_card_cannot_be_transferred(self):
        """Solo se transfieren tarjetas ya en cobranza o enrutadas."""
        card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        with self.assertRaises(UserError):
            self._wizard(card).action_confirm_transfer()

    def test_collector_cannot_use_the_transfer_wizard(self):
        """Un cobrador no puede transferir tarjetas: es potestad del administrador (RN-04)."""
        cards = self._active_cards(1)
        with self.assertRaises(AccessError):
            self.env["cvi.transfer.wizard"].with_user(self.collector_user).create({
                "card_ids": [(6, 0, cards.ids)],
                "collector_dest_id": self.collector_dest.id,
                "reason": "Intento no autorizado",
            })
