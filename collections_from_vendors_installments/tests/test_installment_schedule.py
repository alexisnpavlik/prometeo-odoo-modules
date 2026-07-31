# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviInstallmentSchedule(CviCommon):

    def setUp(self):
        super().setUp()
        # date_sale fija en el pasado; sin tolerancia las cuotas quedarían
        # "overdue" en vez de "pending", rompiendo asserts que no tienen que
        # ver con mora. Los tests que sí ejercitan mora pisan este valor.
        self.company.cvi_overdue_days = 3650  # ~10 años

    def _card(self, count=12, amount=10000.0, frequency="monthly", **kwargs):
        """Tarjeta en borrador con un plan creado a medida para el caso bajo prueba.

        Cada test necesita una combinación distinta de cantidad de cuotas y frecuencia,
        así que el plan se arma acá en vez de usar los del fixture compartido.
        """
        plan = self.env["cvi.product.plan"].create({
            "product_tmpl_id": self.product.product_tmpl_id.id,
            "name": "Plan %s x %s %s" % (count, amount, frequency),
            "installment_count": count,
            "installment_amount": amount,
            "frequency": frequency,
        })
        vals = {
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "plan_id": plan.id,
            "date_sale": "2026-01-15",
            "charge_day_month": 10,
        }
        vals.update(kwargs)
        return self.env["cvi.card"].create(vals)

    def test_generates_exactly_n_installments(self):
        """Se generan tantas cuotas como indica el plan elegido."""
        card = self._card(count=12)
        card._cvi_generate_installments()
        self.assertEqual(len(card.installment_ids), 12)

    def test_first_installment_due_on_sale_date(self):
        """La cuota 1 vence el día de la venta: la cobra el vendedor en el acto (RN-01)."""
        card = self._card(date_sale="2026-01-15")
        card._cvi_generate_installments()
        first = card.installment_ids.filtered(lambda i: i.sequence == 1)
        self.assertEqual(str(first.date_due), "2026-01-15")
        self.assertTrue(first.is_commission)

    def test_only_first_installment_is_commission(self):
        """Solo la cuota 1 es comisión del vendedor."""
        card = self._card(count=12)
        card._cvi_generate_installments()
        commissions = card.installment_ids.filtered("is_commission")
        self.assertEqual(len(commissions), 1)
        self.assertEqual(commissions.sequence, 1)

    def test_monthly_second_installment_falls_next_month_on_charge_day(self):
        """Venta el 15/01 con día de cobro 10: la cuota 2 vence el 10/02."""
        card = self._card(count=3, date_sale="2026-01-15", charge_day_month=10)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(str(second.date_due), "2026-02-10")

    def test_monthly_clamps_to_last_day_of_short_month(self):
        """Día de cobro 31 en febrero: vence el 28 (2026 no es bisiesto)."""
        card = self._card(count=3, date_sale="2026-01-15", charge_day_month=31)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(str(second.date_due), "2026-02-28")

    def test_monthly_installments_advance_one_month_each(self):
        """Las cuotas mensuales avanzan mes a mes sobre el mismo día."""
        card = self._card(count=4, date_sale="2026-01-15", charge_day_month=10)
        card._cvi_generate_installments()
        dues = card.installment_ids.sorted("sequence").mapped("date_due")
        self.assertEqual(
            [str(d) for d in dues],
            ["2026-01-15", "2026-02-10", "2026-03-10", "2026-04-10"],
        )

    def test_weekly_second_installment_is_next_occurrence(self):
        """Venta el jueves 15/01/2026 con cobro los miércoles: la cuota 2 vence el 21/01."""
        card = self._card(
            count=3, frequency="weekly", date_sale="2026-01-15", charge_day_week="2"
        )
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(str(second.date_due), "2026-01-21")

    def test_weekly_same_weekday_as_sale_skips_to_next_week(self):
        """Si el día de cobro es el mismo día de la semana que la venta, salta 7 días."""
        card = self._card(
            count=3, frequency="weekly", date_sale="2026-01-15", charge_day_week="3"
        )
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(str(second.date_due), "2026-01-22")

    def test_weekly_installments_advance_seven_days(self):
        """Las cuotas semanales avanzan de a 7 días."""
        card = self._card(
            count=4, frequency="weekly", date_sale="2026-01-15", charge_day_week="2"
        )
        card._cvi_generate_installments()
        dues = card.installment_ids.sorted("sequence").mapped("date_due")
        self.assertEqual(
            [str(d) for d in dues],
            ["2026-01-15", "2026-01-21", "2026-01-28", "2026-02-04"],
        )

    def test_every_installment_is_worth_the_plan_amount(self):
        """Todas las cuotas valen lo que dice el plan: no hay resto que repartir."""
        card = self._card(count=3, amount=33333.33)
        card._cvi_generate_installments()
        amounts = card.installment_ids.sorted("sequence").mapped("amount")
        self.assertEqual(amounts, [33333.33, 33333.33, 33333.33])

    def test_installment_amounts_sum_to_total(self):
        """La suma de las cuotas iguala exactamente el precio total de la tarjeta."""
        card = self._card(count=3, amount=33333.33)
        card._cvi_generate_installments()
        self.assertEqual(
            sum(card.installment_ids.mapped("amount")), card.amount_total
        )

    def test_regenerating_replaces_previous_schedule(self):
        """Regenerar el calendario en borrador reemplaza las cuotas anteriores."""
        card = self._card(count=3)
        card._cvi_generate_installments()
        card.line_ids[0].plan_id = self.plan_12
        card._cvi_generate_installments()
        self.assertEqual(len(card.installment_ids), 12)

    def test_installment_starts_pending(self):
        """Una cuota recién generada está pendiente y su residual es el monto total."""
        card = self._card(count=3)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(second.state, "pending")
        self.assertEqual(second.amount_paid, 0.0)
        self.assertEqual(second.amount_residual, second.amount)

    def test_postpone_moves_due_date(self):
        """El cliente pide correr la próxima fecha de cobro y la cuota se reprograma."""
        card = self._card(count=3)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        second.action_postpone("2026-02-20")
        self.assertEqual(str(second.date_due), "2026-02-20")

    def test_postpone_before_sale_date_is_rejected(self):
        """No se puede reprogramar una cuota a antes de la fecha de venta."""
        card = self._card(count=3)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        with self.assertRaises(UserError):
            second.action_postpone("2026-01-01")

    def test_overdue_when_past_due_without_tolerance(self):
        """Sin tolerancia, una cuota impaga vencida ayer figura como vencida."""
        self.company.cvi_overdue_days = 0
        card = self._card(count=3, date_sale="2020-01-15", charge_day_month=10)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(second.state, "overdue")

    def test_tolerance_days_delay_overdue_flag(self):
        """Con 10000 días de tolerancia, la misma cuota vieja sigue pendiente."""
        self.company.cvi_overdue_days = 10000
        card = self._card(count=3, date_sale="2020-01-15", charge_day_month=10)
        card._cvi_generate_installments()
        second = card.installment_ids.filtered(lambda i: i.sequence == 2)
        self.assertEqual(second.state, "pending")
