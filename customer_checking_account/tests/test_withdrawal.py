# -*- coding: utf-8 -*-
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form

from .common import CcaCommon


class TestWithdrawal(CcaCommon):

    def _withdrawal(self, qty=3, **vals):
        """Crea un retiro en borrador con `qty` unidades del producto de prueba."""
        values = {
            "partner_id": self.partner.id,
            "date": date(2026, 1, 15),
            "first_due_date": date(2027, 2, 15),
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": qty})],
        }
        values.update(vals)
        return self.env["cca.withdrawal"].create(values)

    def test_any_partner_gets_account(self):
        """Cualquier contacto puede retirar: la cuenta se crea sola."""
        withdrawal = self._withdrawal()
        self.assertEqual(withdrawal.account_id.partner_id, self.partner)
        self.assertTrue(withdrawal.name.startswith("RC/"))

    def test_line_price_defaults_to_list_price(self):
        """El precio de la línea sale de list_price."""
        withdrawal = self._withdrawal(qty=2)
        self.assertEqual(withdrawal.line_ids.price_unit, 100.0)
        self.assertEqual(withdrawal.amount_untaxed, 200.0)

    def test_surcharge_applied_to_total(self):
        """El recargo % se suma al subtotal."""
        withdrawal = self._withdrawal(qty=3, surcharge_percent=10.0)
        self.assertEqual(withdrawal.amount_untaxed, 300.0)
        self.assertEqual(withdrawal.amount_surcharge, 30.0)
        self.assertEqual(withdrawal.amount_total, 330.0)

    def test_single_installment_no_surcharge(self):
        """Caso común: sin recargo y 1 cuota, la cuota es igual al subtotal."""
        withdrawal = self._withdrawal(qty=1)
        self.assertEqual(len(withdrawal.installment_ids), 1)
        self.assertEqual(withdrawal.installment_ids.amount, 100.0)
        self.assertEqual(withdrawal.installment_ids.date_due, date(2027, 2, 15))

    def test_last_installment_absorbs_rounding(self):
        """100 en 3 cuotas: 33.33, 33.33, 33.34."""
        withdrawal = self._withdrawal(qty=1, installment_count=3)
        amounts = withdrawal.installment_ids.sorted("sequence").mapped("amount")
        self.assertEqual(amounts, [33.33, 33.33, 33.34])
        self.assertAlmostEqual(sum(amounts), withdrawal.amount_total)

    def test_monthly_and_weekly_due_dates(self):
        """Los vencimientos avanzan por mes o por semana desde la primera fecha."""
        monthly = self._withdrawal(installment_count=3)
        self.assertEqual(
            monthly.installment_ids.sorted("sequence").mapped("date_due"),
            [date(2027, 2, 15), date(2027, 3, 15), date(2027, 4, 15)],
        )
        weekly = self._withdrawal(installment_count=2, frequency="weekly")
        self.assertEqual(
            weekly.installment_ids.sorted("sequence").mapped("date_due"),
            [date(2027, 2, 15), date(2027, 2, 22)],
        )

    def test_write_lines_resyncs_draft_installments(self):
        """Cambiar líneas por código en borrador regenera las cuotas."""
        withdrawal = self._withdrawal(qty=1, installment_count=2)
        withdrawal.write({"line_ids": [(1, withdrawal.line_ids.id, {"quantity": 4})]})
        self.assertEqual(sum(withdrawal.installment_ids.mapped("amount")), 400.0)

    def test_write_surcharge_resyncs_draft_installments(self):
        """Cambiar el recargo en borrador regenera las cuotas."""
        withdrawal = self._withdrawal(qty=1, installment_count=2)
        withdrawal.surcharge_percent = 20.0
        self.assertEqual(sum(withdrawal.installment_ids.mapped("amount")), 120.0)

    def test_onchange_previews_installments(self):
        """En el formulario, las cuotas se recalculan al escribir el recargo y la cantidad."""
        form = Form(self.env["cca.withdrawal"])
        form.partner_id = self.partner
        form.first_due_date = date(2027, 2, 15)
        with form.line_ids.new() as line:
            line.product_id = self.product
            line.quantity = 2
        form.surcharge_percent = 50.0
        form.installment_count = 4
        self.assertEqual(form.amount_total, 300.0)
        self.assertEqual(len(form.installment_ids), 4)
        self.assertEqual(form.installment_ids._records[0]["amount"], 75.0)

    def test_negative_surcharge_rejected(self):
        """El recargo no puede ser negativo."""
        with self.assertRaises(ValidationError):
            self._withdrawal(surcharge_percent=-5.0)

    def test_zero_installments_rejected(self):
        """La cantidad de cuotas tiene que ser al menos 1."""
        with self.assertRaises(ValidationError):
            self._withdrawal(installment_count=0)

    def test_default_first_due_date_is_next_month(self):
        """Sin fecha explícita, la primera cuota vence en un mes."""
        withdrawal = self.env["cca.withdrawal"].create({"partner_id": self.partner.id})
        today = withdrawal.date
        self.assertEqual(withdrawal.first_due_date, today + relativedelta(months=1))

    def test_unlink_only_draft_or_cancel(self):
        """Un retiro en borrador se puede borrar."""
        withdrawal = self._withdrawal()
        withdrawal.unlink()
        self.assertFalse(withdrawal.exists())
