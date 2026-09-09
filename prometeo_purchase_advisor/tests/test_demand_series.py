# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.tests import tagged

from .common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestDemandSeries(PurchaseAdvisorCommon):
    """Fase 2: lectura de movimientos y reconstrucción de disponibilidad."""

    def test_intercompany_delivery_is_not_customer_demand(self):
        """Una salida a cliente cuyo contacto es una compañía es un traslado."""
        other, _warehouse = self._isolated_company()
        move = self._make_move(self.product_a, 50, self._today() - timedelta(days=2))
        picking = self.env["stock.picking"].create({
            "partner_id": other.partner_id.id,
            "picking_type_id": self.warehouse.out_type_id.id,
            "location_id": move.location_id.id,
            "location_dest_id": move.location_dest_id.id,
        })
        move.picking_id = picking
        self._make_move(self.product_a, 3, self._today() - timedelta(days=1))
        series = self._build_series(None, self.product_a, lookback=30)
        self.assertEqual(series.total_qty(self.product_a.id), 3)

    def test_daily_demand_is_aggregated_per_day(self):
        today = self._today()
        self._make_move(self.product_a, 3, today - timedelta(days=1))
        self._make_move(self.product_a, 7, today - timedelta(days=1))
        self._make_move(self.product_a, 5, today - timedelta(days=2))
        series = self._build_series(None, self.product_a, lookback=30)

        per_day = series.qty[self.product_a.id]
        self.assertAlmostEqual(per_day[today - timedelta(days=1)], 10.0)
        self.assertAlmostEqual(per_day[today - timedelta(days=2)], 5.0)
        self.assertAlmostEqual(series.total_qty(self.product_a.id), 15.0)

    def test_returns_are_subtracted(self):
        today = self._today()
        self._make_move(self.product_a, 10, today - timedelta(days=3))
        self._make_return(self.product_a, 4, today - timedelta(days=2))
        series = self._build_series(None, self.product_a, lookback=30)
        self.assertAlmostEqual(series.total_qty(self.product_a.id), 6.0)

    def test_moves_count_only_outgoing(self):
        today = self._today()
        self._make_move(self.product_a, 10, today - timedelta(days=3))
        self._make_move(self.product_a, 10, today - timedelta(days=2))
        self._make_return(self.product_a, 4, today - timedelta(days=2))
        series = self._build_series(None, self.product_a, lookback=30)
        self.assertEqual(series.moves(self.product_a.id), 2)

    def test_current_day_is_excluded(self):
        """La ventana termina ayer: el día en curso está incompleto."""
        today = self._today()
        self._make_move(self.product_a, 99, today)
        self._make_move(self.product_a, 5, today - timedelta(days=1))
        series = self._build_series(None, self.product_a, lookback=30)
        self.assertAlmostEqual(series.total_qty(self.product_a.id), 5.0)

    def test_history_starts_at_first_move(self):
        """Los días previos al alta del producto no son demanda cero."""
        today = self._today()
        self._sell_daily(self.product_a, 10, 15, 1)
        series = self._build_series(None, self.product_a, lookback=90)

        self.assertEqual(series.first_move_date[self.product_a.id],
                         today - timedelta(days=14))
        self.assertEqual(series.history_days(self.product_a.id), 14)

    def test_days_without_movement_are_stockouts_when_no_stock(self):
        today = self._today()
        # Vendió del día 90 al 31; los últimos 30 días quedó sin nada.
        self._sell_daily(self.product_a, 10, 91, 31)
        series = self._build_series(None, self.product_a, lookback=90)

        self.assertEqual(series.days_with_stock(self.product_a.id), 60)
        self.assertEqual(len(series.stockout_days[self.product_a.id]), 30)
        self.assertAlmostEqual(series.stockout_ratio(self.product_a.id), 30 / 90)
        self.assertNotIn(today - timedelta(days=45),
                         series.stockout_days[self.product_a.id])

    def test_day_with_a_sale_always_counts_as_having_stock(self):
        """Vendió y se agotó: ese día tuvo stock, no fue un quiebre."""
        today = self._today()
        self._make_move(self.product_a, 10, today - timedelta(days=5))
        series = self._build_series(None, self.product_a, lookback=30)
        self.assertNotIn(today - timedelta(days=5),
                         series.stockout_days.get(self.product_a.id, set()))
        self.assertEqual(series.days_with_stock(self.product_a.id), 1)

    def test_receipt_keeps_earlier_days_with_stock(self):
        """Una recepción explica el stock: los días previos no son quiebre."""
        today = self._today()
        self._make_move(self.product_a, 5, today - timedelta(days=20), outgoing=False)
        self._make_move(self.product_a, 5, today - timedelta(days=2))
        series = self._build_series(None, self.product_a, lookback=90)

        missing = series.stockout_days.get(self.product_a.id, set())
        self.assertNotIn(today - timedelta(days=10), missing,
                         "Entre la recepción y la venta hubo stock")
        self.assertIn(today - timedelta(days=25), missing,
                      "Antes de la recepción no había nada")

    def test_other_warehouse_is_excluded(self):
        other = self.env["stock.warehouse"].create({
            "name": "Sucursal 2", "code": "SUC2", "company_id": self.company.id,
        })
        today = self._today()
        self._make_move(self.product_a, 10, today - timedelta(days=2))
        self._make_move(self.product_a, 999, today - timedelta(days=2),
                        warehouse=other)
        series = self._build_series(None, self.product_a, lookback=30)
        self.assertAlmostEqual(series.total_qty(self.product_a.id), 10.0)

    def test_daily_values_can_skip_stockout_days(self):
        self._sell_daily(self.product_a, 10, 91, 31)
        series = self._build_series(None, self.product_a, lookback=90)

        with_gaps = series.daily_values(self.product_a.id)
        without_gaps = series.daily_values(self.product_a.id, only_with_stock=True)
        self.assertEqual(len(with_gaps), 90)
        self.assertEqual(len(without_gaps), 60)
        self.assertTrue(all(value == 10.0 for value in without_gaps))

    def test_empty_product_list_returns_empty_series(self):
        series = self._build_series(None, self.env["product.product"], lookback=30)
        self.assertEqual(series.product_ids, [])
        self.assertEqual(series.qty, {})
