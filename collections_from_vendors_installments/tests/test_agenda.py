# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviAgenda(CviCommon):

    def setUp(self):
        super().setUp()
        self.partner.write({
            "street": "Av. Siempreviva 742",
            "city": "Rosario",
        })
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2020-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()
        self.card.action_accept()

    def _agenda(self):
        """Cuotas que el cobrador tiene que cobrar hasta hoy (HU-14)."""
        today = fields.Date.context_today(self.env.user)
        return self.env["cvi.installment"].search([
            ("card_id.collector_id", "=", self.collector_user.id),
            ("card_id.state", "=", "active"),
            ("state", "in", ("pending", "partial", "overdue")),
            ("date_due", "<=", today),
        ])

    def test_agenda_lists_due_installments(self):
        """La agenda muestra las cuotas vencidas o que vencen hoy."""
        agenda = self._agenda()
        self.assertEqual(len(agenda), 2)
        self.assertEqual(set(agenda.mapped("sequence")), {2, 3})

    def test_agenda_excludes_the_commission_installment(self):
        """La cuota que cobró el vendedor no aparece en la agenda del cobrador (HU-09)."""
        agenda = self._agenda()
        self.assertNotIn(1, agenda.mapped("sequence"))

    def test_agenda_excludes_paid_installments(self):
        """Una cuota ya cobrada sale de la agenda."""
        payment = self.env["cvi.payment"].create({
            "card_id": self.card.id, "amount": 10000.0,
        })
        payment.action_post()
        self.assertNotIn(2, self._agenda().mapped("sequence"))

    def test_installment_exposes_customer_address(self):
        """Cada línea de la agenda trae la dirección del cliente (HU-14)."""
        installment = self._agenda()[0]
        self.assertEqual(installment.street, "Av. Siempreviva 742")

    def test_installment_exposes_card_balance(self):
        """El cobrador ve el saldo total de la tarjeta desde la agenda (HU-14)."""
        installment = self._agenda()[0]
        self.assertEqual(installment.card_residual, self.card.amount_residual)

    def test_map_url_is_built_from_the_address(self):
        """El link al mapa se arma con la dirección del cliente (HU-14)."""
        installment = self._agenda()[0]
        self.assertIn("google.com/maps", installment.map_url)
        self.assertIn("Siempreviva", installment.map_url)

    def test_map_url_is_empty_without_address(self):
        """Sin dirección cargada no se ofrece un link roto."""
        self.partner.write({"street": False, "city": False, "zip": False})
        installment = self._agenda()[0]
        self.assertFalse(installment.map_url)

    def test_open_map_returns_url_action(self):
        """El botón del mapa devuelve una acción que abre el link (HU-14)."""
        installment = self._agenda()[0]
        action = installment.action_open_map()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["target"], "new")
