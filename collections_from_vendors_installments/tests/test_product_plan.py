# -*- coding: utf-8 -*-
import psycopg2

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviProductPlan(CviCommon):

    def setUp(self):
        super().setUp()
        # Mueble propio de esta clase: `cls.product` del fixture ya trae tres planes
        # cargados, y estos tests cuentan y nombran planes desde cero.
        self.furniture = self.env["product.product"].create({
            "name": "Cómoda 4 cajones",
            "type": "consu",
            "is_storable": True,
            "list_price": 90000.0,
        })

    def _plan(self, **kwargs):
        """Plan de cuotas del mueble de test, sobreescribible."""
        vals = {
            "product_tmpl_id": self.furniture.product_tmpl_id.id,
            "name": "12 cuotas",
            "installment_count": 12,
            "installment_amount": 13500.0,
            "frequency": "monthly",
        }
        vals.update(kwargs)
        return self.env["cvi.product.plan"].create(vals)

    def test_total_is_count_times_amount(self):
        """El total del plan se calcula: cantidad de cuotas por importe de cuota."""
        plan = self._plan(installment_count=12, installment_amount=13500.0)
        self.assertEqual(plan.amount_total, 162000.0)

    def test_total_updates_when_amount_changes(self):
        """Cambiar el importe de cuota recalcula el total del plan."""
        plan = self._plan(installment_count=12, installment_amount=13500.0)
        plan.installment_amount = 15000.0
        self.assertEqual(plan.amount_total, 180000.0)

    def test_weekly_plan_is_supported(self):
        """Un plan puede ser semanal en vez de mensual."""
        plan = self._plan(name="20 semanas", installment_count=20,
                          installment_amount=7000.0, frequency="weekly")
        self.assertEqual(plan.frequency, "weekly")
        self.assertEqual(plan.amount_total, 140000.0)

    def test_both_modalities_coexist_on_the_same_product(self):
        """Un mismo mueble ofrece planes mensuales y semanales a la vez."""
        self._plan(name="12 cuotas", frequency="monthly")
        self._plan(name="20 semanas", installment_count=20,
                   installment_amount=7000.0, frequency="weekly")
        frequencies = self.furniture.product_tmpl_id.cvi_plan_ids.mapped("frequency")
        self.assertEqual(set(frequencies), {"monthly", "weekly"})

    def test_installment_amount_is_not_a_division_of_the_list_price(self):
        """El importe de cuota lleva el interés adentro: no divide ningún precio.

        El mueble vale $90.000 de contado y el plan de 6 cuotas suma $132.000. El módulo
        acepta esa diferencia sin chistar porque el recargo es parte del importe cargado.
        """
        self.assertEqual(self.furniture.list_price, 90000.0)
        plan = self._plan(name="6 cuotas", installment_count=6, installment_amount=22000.0)
        self.assertEqual(plan.amount_total, 132000.0)
        self.assertGreater(plan.amount_total, self.furniture.list_price)

    def test_list_price_change_does_not_touch_the_plans(self):
        """Cambiar el precio de lista del mueble no altera los planes ya cargados."""
        plan = self._plan(name="6 cuotas", installment_count=6, installment_amount=22000.0)
        self.furniture.list_price = 150000.0
        self.assertEqual(plan.installment_amount, 22000.0)
        self.assertEqual(plan.amount_total, 132000.0)

    def test_product_lists_its_plans(self):
        """Los planes cuelgan de la ficha del mueble (HU-05)."""
        self._plan(name="6 cuotas", installment_count=6, installment_amount=22000.0)
        self._plan(name="12 cuotas", installment_count=12, installment_amount=13500.0)
        template = self.furniture.product_tmpl_id
        self.assertEqual(len(template.cvi_plan_ids), 2)
        self.assertEqual(template.cvi_plan_count, 2)

    def test_plan_count_ignores_archived_plans(self):
        """Un plan archivado deja de ofrecerse y no se cuenta."""
        plan = self._plan(name="6 cuotas", installment_count=6, installment_amount=22000.0)
        self._plan(name="12 cuotas")
        plan.active = False
        self.assertEqual(self.furniture.product_tmpl_id.cvi_plan_count, 1)

    def test_installment_count_must_be_positive(self):
        """No existe un plan de cero cuotas."""
        with self.assertRaises(ValidationError):
            self._plan(installment_count=0)

    def test_installment_amount_must_be_positive(self):
        """No existe un plan con cuota de importe cero."""
        with self.assertRaises(ValidationError):
            self._plan(installment_amount=0.0)

    def test_plan_name_is_unique_per_product(self):
        """Un mismo mueble no puede tener dos planes con el mismo nombre."""
        self._plan(name="12 cuotas")
        with self.assertRaises(psycopg2.errors.UniqueViolation), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self._plan(name="12 cuotas", installment_amount=14000.0)

    def test_same_plan_name_allowed_on_another_product(self):
        """Dos muebles distintos sí pueden tener un plan llamado igual."""
        self._plan(name="12 cuotas")
        other = self.env["product.product"].create({
            "name": "Mesa de luz", "type": "consu", "is_storable": True,
        })
        plan = self._plan(name="12 cuotas", product_tmpl_id=other.product_tmpl_id.id,
                          installment_amount=4000.0)
        self.assertEqual(plan.amount_total, 48000.0)

    def test_display_name_shows_the_installment_amount(self):
        """El plan se muestra con su importe, para elegirlo de un vistazo en la calle."""
        plan = self._plan(name="12 cuotas", installment_count=12, installment_amount=13500.0)
        self.assertIn("13.500", plan.display_name.replace(",", "."))
        self.assertIn("12 cuotas", plan.display_name)
