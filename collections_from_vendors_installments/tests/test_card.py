# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCard(CviCommon):

    def _card(self, **kwargs):
        """Tarjeta en borrador con valores mínimos, sobreescribibles."""
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": self.plan_12.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        return self.env["cvi.card"].create(vals)

    def test_sequence_is_assigned_on_create(self):
        """Al crear, la tarjeta recibe una referencia de la secuencia."""
        card = self._card()
        self.assertTrue(card.name.startswith("TARJ/"))
        self.assertNotEqual(card.name, "Nuevo")

    def test_new_card_starts_in_draft(self):
        """Una tarjeta nueva arranca en borrador."""
        self.assertEqual(self._card().state, "draft")

    def test_plan_fills_installment_count(self):
        """Elegir el plan completa la cantidad de cuotas (HU-05)."""
        self.assertEqual(self._card(plan_id=self.plan_12.id).installment_count, 12)

    def test_plan_fills_installment_amount(self):
        """Elegir el plan completa el importe de cuota, que no se carga a mano (HU-05)."""
        self.assertEqual(self._card(plan_id=self.plan_12.id).installment_amount, 10000.0)

    def test_plan_fills_frequency(self):
        """La frecuencia de cobro viene con el plan, no se elige aparte (HU-06)."""
        card = self._card(plan_id=self.plan_weekly.id, charge_day_week="2",
                          charge_day_month=0)
        self.assertEqual(card.frequency, "weekly")

    def test_total_is_derived_from_the_plan(self):
        """El precio total sale de cantidad de cuotas por importe: 12 x 10.000."""
        self.assertEqual(self._card(plan_id=self.plan_12.id).amount_total, 120000.0)

    def test_changing_the_plan_repricing_the_card(self):
        """Cambiar de plan en la línea reescribe cuotas, importe y total.

        El plan vive en la línea desde que una venta puede llevar varios muebles: la
        cabecera lo refleja, pero escribirlo ahí no cambia nada.
        """
        card = self._card(plan_id=self.plan_12.id)
        card.line_ids[0].plan_id = self.plan_3.id
        self.assertEqual(card.installment_count, 3)
        self.assertEqual(card.installment_amount, 10000.0)
        self.assertEqual(card.amount_total, 30000.0)

    def test_plan_of_another_product_is_rejected(self):
        """No se puede vender un mueble con el plan de otro mueble."""
        other = self.env["product.product"].create({
            "name": "Mesa de luz", "type": "consu", "is_storable": True,
        })
        other_plan = self.env["cvi.product.plan"].create({
            "product_tmpl_id": other.product_tmpl_id.id,
            "name": "6 cuotas",
            "installment_count": 6,
            "installment_amount": 4000.0,
            "frequency": "monthly",
        })
        with self.assertRaises(ValidationError):
            self._card(product_id=self.product.id, plan_id=other_plan.id)

    def test_manager_can_override_the_plan_amount(self):
        """El administrador puede vender con un importe distinto al del plan."""
        card = self._card(plan_id=self.plan_12.id, installment_amount=11000.0)
        self.assertEqual(card.line_ids[0].installment_amount, 11000.0)
        self.assertEqual(card.installment_amount, 11000.0)
        self.assertEqual(card.amount_total, 132000.0)

    def test_vendor_cannot_override_the_plan_amount(self):
        """Un vendedor no puede cambiar el precio que fija el plan."""
        with self.assertRaises(ValidationError):
            self.env["cvi.card"].with_user(self.vendor_user).create({
                "partner_id": self.partner.id,
                "vendor_id": self.vendor_user.id,
                "product_id": self.product.id,
                "plan_id": self.plan_12.id,
                "date_sale": "2026-01-15",
                "charge_day_month": 10,
                "installment_amount": 8000.0,
            })

    def test_vendor_cannot_override_the_installment_count(self):
        """Un vendedor tampoco puede cambiar en cuántas cuotas vende."""
        with self.assertRaises(ValidationError):
            self.env["cvi.card"].with_user(self.vendor_user).create({
                "partner_id": self.partner.id,
                "vendor_id": self.vendor_user.id,
                "product_id": self.product.id,
                "plan_id": self.plan_12.id,
                "date_sale": "2026-01-15",
                "charge_day_month": 10,
                "installment_count": 24,
            })

    def test_vendor_selling_at_the_plan_price_is_accepted(self):
        """Vendiendo al precio del plan, el vendedor carga la venta sin problemas."""
        card = self.env["cvi.card"].with_user(self.vendor_user).create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": self.plan_12.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
        })
        self.assertEqual(card.amount_total, 120000.0)

    def test_charge_day_display_monthly(self):
        """Con frecuencia mensual el día de cobro se muestra como día del mes."""
        card = self._card(plan_id=self.plan_12.id, charge_day_month=10)
        self.assertEqual(card.charge_day_display, "Día 10 de cada mes")

    def test_charge_day_display_weekly(self):
        """Con frecuencia semanal el día de cobro se muestra como día de la semana."""
        card = self._card(plan_id=self.plan_weekly.id, charge_day_week="2",
                          charge_day_month=0)
        self.assertEqual(card.charge_day_display, "Todos los miércoles")

    def test_charge_day_month_out_of_range_is_rejected(self):
        """Un día del mes fuera de 1..31 no se acepta."""
        with self.assertRaises(ValidationError):
            self._card(plan_id=self.plan_12.id, charge_day_month=45)

    def test_frequency_not_allowed_by_company_is_rejected(self):
        """Si la empresa solo permite mensual, un plan semanal no se puede vender (HU-31)."""
        self.company.cvi_allowed_frequencies = "monthly"
        with self.assertRaises(ValidationError):
            self._card(plan_id=self.plan_weekly.id, charge_day_week="2",
                       charge_day_month=0)
