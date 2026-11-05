# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CcaPosCommon


@tagged("post_install", "-at_install")
class TestCcaPosInstall(CcaPosCommon):

    def test_payment_product_exists(self):
        """El producto de pago existe como servicio vendible en POS y sin impuestos."""
        product = self.env.ref("customer_checking_account_pos.product_cca_pos_payment")
        self.assertEqual(product.type, "service")
        self.assertTrue(product.available_in_pos)
        self.assertFalse(product.taxes_id)
        self.assertEqual(self.config.cca_payment_product_id, product)

    def test_cc_flag_requires_pay_later(self):
        """Un método con diario no puede ser de cuenta corriente."""
        with self.assertRaises(ValidationError):
            self.bank_pm1.cca_is_checking_account = True

    def test_single_cc_method_per_config(self):
        """Una caja no admite dos métodos de cuenta corriente."""
        self.bank_split_pm1.write({"journal_id": False})
        with self.assertRaises(ValidationError):
            self.bank_split_pm1.cca_is_checking_account = True

    def test_company_defaults(self):
        """Los valores de financiación tienen defaults."""
        self.assertEqual(self.company.cca_pos_installment_count, 1)
        self.assertEqual(self.company.cca_pos_first_due_days, 30)
        self.assertEqual(self.company.cca_pos_frequency, "monthly")
        self.assertEqual(self.company.cca_pos_surcharge_percent, 0.0)

    def test_pos_loads_cc_flag(self):
        """El POS carga la marca cc y los datos de financiación."""
        self.assertIn(
            "cca_is_checking_account",
            self.env["pos.payment.method"]._load_pos_data_fields(self.config.id),
        )
        company_fields = self.env["res.company"]._load_pos_data_fields(self.config.id)
        for name in ("cca_pos_surcharge_percent", "cca_pos_installment_count",
                     "cca_pos_first_due_days", "cca_pos_frequency"):
            self.assertIn(name, company_fields)
