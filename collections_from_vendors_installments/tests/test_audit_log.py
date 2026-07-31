# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviAuditLog(CviCommon):
    """Verifica que el registro de auditoría (RN-08, `_cvi_log`) funcione tanto
    para usuarios con email como para vendedores/cobradores de calle sin email.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.no_email_collector = cls.env["res.users"].create({
            "name": "Cobrador Sin Email",
            "login": "cvi_collector_no_email",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [
                cls.env.ref("collections_from_vendors_installments.group_cvi_collector").id,
                cls.env.ref("base.group_user").id,
            ])],
        })
        # Aseguramos que el partner del usuario no tenga email, sea cual sea
        # el valor por defecto que Odoo le haya puesto al crearlo.
        cls.no_email_collector.partner_id.email = False

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

    def test_accept_without_email_does_not_raise_and_preserves_attribution(self):
        """Un cobrador sin email puede aceptar una tarjeta enrutada (RN-08) y el
        mensaje de auditoría queda atribuido a él, no a OdooBot."""
        self.assertFalse(self.no_email_collector.partner_id.email)
        card = self._confirmed_card(collector_id=self.no_email_collector.id)
        self.assertEqual(card.state, "routed")
        card.with_user(self.no_email_collector).action_accept()
        self.assertEqual(card.state, "active")
        last_message = card.message_ids.sorted("id", reverse=True)[0]
        self.assertEqual(last_message.author_id, self.no_email_collector.partner_id)

    def test_accept_with_email_still_works(self):
        """El camino normal (usuario con email) sigue funcionando sin cambios."""
        self.assertTrue(self.collector_user.partner_id.email)
        card = self._confirmed_card(collector_id=self.collector_user.id)
        card.with_user(self.collector_user).action_accept()
        self.assertEqual(card.state, "active")
        last_message = card.message_ids.sorted("id", reverse=True)[0]
        self.assertEqual(last_message.author_id, self.collector_user.partner_id)
