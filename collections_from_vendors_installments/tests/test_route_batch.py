# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviRouteBatch(CviCommon):

    def _confirmed_cards(self, how_many):
        """`how_many` tarjetas confirmadas sin cobrador asignado."""
        cards = self.env["cvi.card"]
        for _index in range(how_many):
            card = self.env["cvi.card"].create({
                "partner_id": self.partner.id,
                "vendor_id": self.vendor_user.id,
                "product_id": self.product.id,
                "date_sale": "2026-01-15",
                "plan_id": self.plan_3.id,
                "charge_day_month": 10,
            })
            card.action_confirm()
            cards |= card
        return cards

    def test_batch_routes_every_selected_card(self):
        """Enviar 5 tarjetas juntas las deja todas enrutadas al mismo cobrador (HU-11)."""
        cards = self._confirmed_cards(5)
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        wizard.action_confirm_route()
        self.assertEqual(set(cards.mapped("state")), {"routed"})
        self.assertEqual(set(cards.mapped("collector_id")), {self.collector_user})

    def test_card_count_reflects_selection(self):
        """El wizard muestra cuántas tarjetas se van a enviar."""
        cards = self._confirmed_cards(3)
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        self.assertEqual(wizard.card_count, 3)

    def test_batch_of_one_hundred_cards(self):
        """El enrutamiento masivo resuelve 100 tarjetas en una sola operación (RNF-05)."""
        cards = self._confirmed_cards(100)
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        wizard.action_confirm_route()
        self.assertEqual(len(cards.filtered(lambda c: c.state == "routed")), 100)

    def test_empty_selection_is_rejected(self):
        """No se puede confirmar el envío sin tarjetas seleccionadas."""
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, [])],
            "collector_id": self.collector_user.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_route()

    def test_already_routed_card_is_rejected(self):
        """Una tarjeta ya enrutada no se puede volver a enviar desde el wizard."""
        cards = self._confirmed_cards(1)
        cards.collector_id = self.collector_user.id
        cards.action_route()
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_route()

    def test_routed_cards_appear_as_pending_for_the_collector(self):
        """Tras el envío, las tarjetas figuran en Pendientes de aceptar del cobrador (HU-12)."""
        cards = self._confirmed_cards(4)
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, cards.ids)],
            "collector_id": self.collector_user.id,
        })
        wizard.action_confirm_route()
        pending = self.env["cvi.card"].search([
            ("collector_id", "=", self.collector_user.id), ("state", "=", "routed"),
        ])
        self.assertEqual(len(pending & cards), 4)

    def test_group_domain_degrades_on_missing_group(self):
        """El helper de dominio devuelve [] si el grupo no existe, sin romper el formulario."""
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, [])],
            "collector_id": self.collector_user.id,
        })
        result = wizard._cvi_group_domain("group_that_does_not_exist")
        self.assertEqual(result, [])

    def test_group_domain_returns_real_group_id(self):
        """El helper de dominio devuelve el dominio correcto para un grupo existente."""
        wizard = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, [])],
            "collector_id": self.collector_user.id,
        })
        domain = wizard._cvi_group_domain("group_cvi_collector")
        self.assertEqual(len(domain), 1)
        self.assertEqual(domain[0][0], "groups_id")
        self.assertEqual(domain[0][1], "in")
        group = self.env.ref("collections_from_vendors_installments.group_cvi_collector")
        self.assertEqual(domain[0][2], group.id)
