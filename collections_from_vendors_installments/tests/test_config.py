# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviConfig(CviCommon):

    def test_default_installments_is_twelve(self):
        """La cantidad de cuotas por defecto arranca en 12 (HU-05)."""
        self.assertEqual(self.company.cvi_default_installments, 12)

    def test_overdue_days_defaults_to_zero(self):
        """Sin tolerancia configurada, una cuota vence al día siguiente del vencimiento."""
        self.assertEqual(self.company.cvi_overdue_days, 0)

    def test_allowed_frequencies_defaults_to_both(self):
        """Por defecto se permiten mensual y semanal (HU-06)."""
        self.assertEqual(self.company.cvi_allowed_frequencies, "both")

    def test_customer_contact_fields_are_required_by_default(self):
        """Una empresa nueva arranca pidiendo todos los datos para poder cobrar."""
        fields = (
            "cvi_customer_mobile_required",
            "cvi_customer_street_required",
            "cvi_customer_city_required",
            "cvi_customer_zip_required",
        )
        for field_name in fields:
            with self.subTest(field=field_name):
                self.assertTrue(self.company[field_name])

    def test_dni_photos_are_optional_by_default(self):
        """Las fotos siguen siendo opcionales hasta que administración las exija."""
        self.assertFalse(self.company.cvi_customer_dni_photos_required)

    def test_settings_writes_through_to_company(self):
        """Cambiar el ajuste en Configuración escribe en la empresa (HU-31)."""
        settings = self.env["res.config.settings"].create({
            "cvi_default_installments": 18,
            "cvi_overdue_days": 5,
            "cvi_allowed_frequencies": "monthly",
            "cvi_customer_mobile_required": False,
            "cvi_customer_street_required": False,
            "cvi_customer_city_required": False,
            "cvi_customer_zip_required": False,
            "cvi_customer_dni_photos_required": True,
        })
        settings.execute()
        self.assertEqual(self.company.cvi_default_installments, 18)
        self.assertEqual(self.company.cvi_overdue_days, 5)
        self.assertEqual(self.company.cvi_allowed_frequencies, "monthly")
        self.assertFalse(self.company.cvi_customer_mobile_required)
        self.assertFalse(self.company.cvi_customer_street_required)
        self.assertFalse(self.company.cvi_customer_city_required)
        self.assertFalse(self.company.cvi_customer_zip_required)
        self.assertTrue(self.company.cvi_customer_dni_photos_required)
