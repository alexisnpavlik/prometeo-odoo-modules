# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviSecurity(CviCommon):

    def setUp(self):
        super().setUp()
        self.other_vendor = self.env["res.users"].create({
            "name": "Vendedor Ajeno",
            "login": "cvi_vendor_other_sec",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_vendor").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.other_vendor._cvi_get_location()
        self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": self.other_vendor.cvi_stock_location_id.id,
            "inventory_quantity": 50,
        }).action_apply_inventory()
        self.manager_user = self.env["res.users"].create({
            "name": "Administrador Test",
            "login": "cvi_manager_sec",
            "email": "manager@test.local",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_manager").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.my_card = self._card(self.vendor_user)
        self.other_card = self._card(self.other_vendor)

    def _card(self, vendor):
        """Tarjeta confirmada del vendedor indicado."""
        card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": vendor.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        card.action_confirm()
        card.action_charge_first_installment()
        return card

    def test_vendor_sees_only_own_cards(self):
        """Un vendedor solo ve sus propias ventas (RN-07)."""
        visible = self.env["cvi.card"].with_user(self.vendor_user).search([])
        self.assertIn(self.my_card, visible)
        self.assertNotIn(self.other_card, visible)

    def test_vendor_sees_installments_of_own_cards_only(self):
        """Un vendedor solo ve las cuotas de sus propias ventas."""
        visible = self.env["cvi.installment"].with_user(self.vendor_user).search([])
        self.assertEqual(set(visible.mapped("card_id")), {self.my_card})

    def test_collector_sees_only_assigned_cards(self):
        """Un cobrador solo ve las tarjetas que le fueron enrutadas (RN-07)."""
        self.my_card.collector_id = self.collector_user.id
        self.my_card.action_route()
        visible = self.env["cvi.card"].with_user(self.collector_user).search([])
        self.assertIn(self.my_card, visible)
        self.assertNotIn(self.other_card, visible)

    def test_collector_sees_routed_cards_before_accepting(self):
        """El cobrador ve las tarjetas pendientes de aceptar (HU-12)."""
        self.my_card.collector_id = self.collector_user.id
        self.my_card.action_route()
        pending = self.env["cvi.card"].with_user(self.collector_user).search([
            ("state", "=", "routed"),
        ])
        self.assertIn(self.my_card, pending)

    def test_collector_stops_seeing_transferred_cards(self):
        """Al transferir la tarjeta, el cobrador de origen deja de verla (HU-30)."""
        self.my_card.collector_id = self.collector_user.id
        self.my_card.action_route()
        self.my_card.action_accept()
        dest = self.env["res.users"].create({
            "name": "Cobrador Nuevo",
            "login": "cvi_collector_new_sec",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.my_card.collector_id = dest.id
        visible = self.env["cvi.card"].with_user(self.collector_user).search([])
        self.assertNotIn(self.my_card, visible)

    def test_collector_does_not_see_unrouted_cards(self):
        """Una tarjeta sin cobrador no aparece en la cartera de nadie."""
        visible = self.env["cvi.card"].with_user(self.collector_user).search([])
        self.assertNotIn(self.my_card, visible)

    def test_manager_sees_everything(self):
        """El administrador ve todas las tarjetas, de todos los vendedores (RN-07)."""
        visible = self.env["cvi.card"].with_user(self.manager_user).search([])
        self.assertIn(self.my_card, visible)
        self.assertIn(self.other_card, visible)

    def test_collector_sees_payments_of_own_portfolio_only(self):
        """Un cobrador solo ve los cobros de las tarjetas de su cartera."""
        self.my_card.collector_id = self.collector_user.id
        self.my_card.action_route()
        self.my_card.action_accept()
        visible = self.env["cvi.payment"].with_user(self.collector_user).search([])
        self.assertEqual(set(visible.mapped("card_id")), {self.my_card})
