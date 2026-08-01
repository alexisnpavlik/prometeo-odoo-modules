# -*- coding: utf-8 -*-
"""Tests que ejercen el permiso real de cada rol (vendedor/cobrador), no el de manager.

`tests/common.py` da `group_cvi_manager` a `cls.env.user`, y ese grupo implica vendedor,
cobrador y `stock.group_stock_user`: los tests del resto del módulo corren como manager
y nunca pisan el filo de permisos real de un vendedor o cobrador. Estos tests usan
`with_user(...)` con `cls.vendor_user` / `cls.collector_user`, que solo tienen su propio
grupo, para exponer exactamente lo que la reseña final encontró roto.
"""
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviRoles(CviCommon):

    def setUp(self):
        super().setUp()
        self.company.cvi_overdue_days = 3650  # sin tolerancia, evita "overdue" espurio

    def test_vendor_can_confirm_own_card_end_to_end(self):
        """Un vendedor real (sin permisos de manager) confirma su propia venta (HU-05/HU-09).

        Este test tiene que fallar con AccessError si se revierte el sudo() acotado en
        `_cvi_create_sale_picking`: sin él, el alta del stock.picking rompe contra
        ir.model.access.csv de `stock`, que solo da create a group_stock_user/manager.
        """
        card = self.env["cvi.card"].with_user(self.vendor_user).create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        card.with_user(self.vendor_user).action_confirm()
        self.assertEqual(card.state, "sold")
        self.assertTrue(card.installment_ids)
        card.with_user(self.vendor_user).action_charge_first_installment()
        commission = card.payment_ids.filtered("is_commission")
        self.assertTrue(commission)
        self.assertEqual(commission.state, "posted")

    def test_collector_can_post_payment_on_accepted_card(self):
        """Un cobrador real cobra una cuota de una tarjeta que aceptó (HU-16)."""
        card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_12.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        card.action_confirm()  # collector_id ya seteado: action_confirm enruta directo
        card.action_charge_first_installment()
        card.with_user(self.collector_user).action_accept()

        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        payment = self.env["cvi.payment"].with_user(self.collector_user).create({
            "card_id": card.id, "amount": second.amount, "date": "2026-02-10",
        })
        payment.with_user(self.collector_user).action_post()

        self.assertEqual(payment.state, "posted")
        second.invalidate_recordset()
        card.invalidate_recordset()
        self.assertEqual(second.state, "paid")
        self.assertEqual(card.amount_residual, card.amount_total - card.installment_amount * 2)

    def test_second_collector_does_not_see_routed_card(self):
        """Aislamiento entre cobradores: una tarjeta enrutada a uno no es visible para otro.

        `test_security.py` prueba aislamiento vendedor-vs-vendedor, pero no cobrador-vs-
        cobrador sobre una tarjeta `routed`: ese es el hueco real detrás del dominio de
        `action_cvi_card_pending_accept`, que depende pura y exclusivamente del ir.rule.
        """
        other_collector = self.env["res.users"].create({
            "name": "Cobrador Ajeno",
            "login": "cvi_collector_other_roles",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        card.action_confirm()  # collector_id ya seteado: action_confirm enruta directo

        visible = self.env["cvi.card"].with_user(other_collector).search([])
        self.assertNotIn(card, visible)
        pending = self.env["cvi.card"].with_user(other_collector).search([
            ("state", "=", "routed"),
        ])
        self.assertNotIn(card, pending)


@tagged("post_install", "-at_install")
class TestCviRoleAssignment(CviCommon):
    """Los tres perfiles asignables: solo vendedor, solo cobrador, y los dos juntos."""

    def _user(self, login, groups):
        return self.env["res.users"].create({
            "name": login,
            "login": login,
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref(
                    "collections_from_vendors_installments.%s" % group
                ).id for group in groups
            ] + [self.env.ref("base.group_user").id])],
        })

    def _card_vals(self, vendor):
        return {
            "customer_id": self.customer.id,
            "vendor_id": vendor.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        }

    # --- los grupos son independientes ---

    def test_a_vendor_is_not_a_collector_anymore(self):
        """Vender y cobrar son dos trabajos distintos: uno no arrastra al otro.

        Si alguien vuelve a encadenar los grupos, todo vendedor recupera en silencio la
        agenda de cobranza y las rendiciones ajenas a su venta.
        """
        self.assertFalse(self.vendor_user.has_group(
            "collections_from_vendors_installments.group_cvi_collector"
        ))

    def test_a_collector_is_not_a_vendor(self):
        self.assertFalse(self.collector_user.has_group(
            "collections_from_vendors_installments.group_cvi_vendor"
        ))

    def test_the_manager_is_both(self):
        manager = self._user("cvi_manager_profile", ["group_cvi_manager"])
        self.assertTrue(manager.has_group(
            "collections_from_vendors_installments.group_cvi_vendor"
        ))
        self.assertTrue(manager.has_group(
            "collections_from_vendors_installments.group_cvi_collector"
        ))

    # --- lo que puede cada perfil ---

    def test_a_collector_cannot_load_a_sale(self):
        with self.assertRaises(AccessError):
            self.env["cvi.card"].with_user(self.collector_user).create(
                self._card_vals(self.vendor_user)
            )

    def test_a_vendor_only_does_not_reach_the_settlements(self):
        """Las rendiciones son del cobrador. Un vendedor puro no rinde nada."""
        with self.assertRaises(AccessError):
            self.env["cvi.settlement"].with_user(self.vendor_user).search([])

    def test_the_hybrid_loads_sales_and_collects(self):
        """El perfil mixto se arma tildando los dos grupos, sin un tercer grupo."""
        hybrid = self._user(
            "cvi_hybrid_profile", ["group_cvi_vendor", "group_cvi_collector"]
        )
        own_sale = self.env["cvi.card"].with_user(hybrid).create(
            self._card_vals(hybrid)
        )
        self.assertTrue(own_sale)

        routed = self.env["cvi.card"].create(dict(
            self._card_vals(self.vendor_user), collector_id=hybrid.id
        ))
        routed.action_confirm()
        routed.with_user(hybrid).action_accept()
        self.assertEqual(routed.state, "active")

    def test_the_hybrid_sees_both_his_sales_and_his_portfolio(self):
        """Las ir.rule de los dos roles se suman, no se pisan (RN-07)."""
        hybrid = self._user(
            "cvi_hybrid_visibility", ["group_cvi_vendor", "group_cvi_collector"]
        )
        sold_by_him = self.env["cvi.card"].create(self._card_vals(hybrid))
        collected_by_him = self.env["cvi.card"].create(dict(
            self._card_vals(self.vendor_user), collector_id=hybrid.id
        ))
        visible = self.env["cvi.card"].with_user(hybrid).search([])
        self.assertIn(sold_by_him, visible)
        self.assertIn(collected_by_him, visible)
