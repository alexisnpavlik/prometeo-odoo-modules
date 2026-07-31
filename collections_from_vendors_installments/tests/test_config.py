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

    def test_settings_writes_through_to_company(self):
        """Cambiar el ajuste en Configuración escribe en la empresa (HU-31)."""
        settings = self.env["res.config.settings"].create({
            "cvi_default_installments": 18,
            "cvi_overdue_days": 5,
            "cvi_allowed_frequencies": "monthly",
        })
        settings.execute()
        self.assertEqual(self.company.cvi_default_installments, 18)
        self.assertEqual(self.company.cvi_overdue_days, 5)
        self.assertEqual(self.company.cvi_allowed_frequencies, "monthly")
