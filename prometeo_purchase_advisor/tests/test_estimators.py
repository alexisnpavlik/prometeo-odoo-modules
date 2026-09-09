# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import PurchaseAdvisorCommon


@tagged("post_install", "-at_install")
class TestEstimators(PurchaseAdvisorCommon):
    """Fase 2: el estimador sobre series sintéticas de respuesta conocida."""

    def _estimate(self, product, model):
        series = self._build_series(model, product)
        return model.estimate(series)[product.id]

    # ------------------------------------------------------------------
    # Caso base
    # ------------------------------------------------------------------
    def test_constant_demand(self):
        """10 por día durante 90 días sin quiebres: 10 por día y desvío cero."""
        self._sell_daily(self.product_a, 10, 91, 1)
        estimate = self._estimate(self.product_a, self._make_model())

        self.assertAlmostEqual(estimate.adu, 10.0, places=3)
        self.assertAlmostEqual(estimate.sigma, 0.0, places=3)
        self.assertEqual(estimate.method_used, "weighted_ma")
        self.assertGreaterEqual(estimate.confidence, 0.8)

    # ------------------------------------------------------------------
    # Corrección por quiebres de stock
    # ------------------------------------------------------------------
    def test_stockout_correction_recovers_real_demand(self):
        """60 días vendiendo 10 y 30 días sin stock: la demanda sigue siendo 10.

        Se usa una sola ventana para aislar el efecto de la corrección: con las
        tres ventanas por defecto entra además la redistribución de pesos, que
        se prueba aparte.
        """
        self._sell_daily(self.product_a, 10, 91, 31)
        model = self._make_model(weight_config="90:1.0", outlier_percentile=0)
        estimate = self._estimate(self.product_a, model)
        self.assertAlmostEqual(estimate.adu, 10.0, places=3)

    def test_without_correction_stockout_days_drag_the_average(self):
        self._sell_daily(self.product_a, 10, 91, 31)
        model = self._make_model(
            weight_config="90:1.0", ignore_stockout_days=False, outlier_percentile=0)
        estimate = self._estimate(self.product_a, model)
        self.assertAlmostEqual(estimate.adu, 600 / 90, places=3)

    def test_empty_windows_redistribute_their_weight(self):
        """El quiebre cae justo en las ventanas cortas: no las deja valer cero."""
        self._sell_daily(self.product_a, 10, 91, 31)
        estimate = self._estimate(self.product_a, self._make_model())

        self.assertAlmostEqual(estimate.adu, 10.0, places=3)
        self.assertTrue(
            any("ventana" in warning for warning in estimate.warnings),
            estimate.warnings,
        )

    def test_stockout_ratio_lowers_confidence(self):
        self._sell_daily(self.product_a, 10, 91, 61)
        estimate = self._estimate(self.product_a, self._make_model())
        self.assertLessEqual(estimate.confidence, 0.4)

    def test_single_stock_day_does_not_dominate_partial_history(self):
        today = self._today()
        self._make_move(self.product_a, 37, today - timedelta(days=73),
                        outgoing=False)
        for qty, offset in ((1, 44), (2, 44), (34, 30)):
            self._make_move(self.product_a, qty, today - timedelta(days=offset))
        model = self._make_model()
        series = self._build_series(model, self.product_a)
        self.assertEqual(series.days_with_stock(self.product_a.id), 44)
        estimate = model.estimate(series)[self.product_a.id]
        self.assertAlmostEqual(estimate.adu, 37 / 44)
        self.assertIn("29 días sin stock", estimate.explanation)
        self.assertIn("73 días calendario", estimate.explanation)
        self.assertNotIn("se recortaron", estimate.explanation)

    def test_sparse_short_window_uses_supported_long_window(self):
        today = self._today()
        self._make_move(self.product_a, 37, today - timedelta(days=90),
                        outgoing=False)
        self._make_move(self.product_a, 3, today - timedelta(days=44))
        self._make_move(self.product_a, 34, today - timedelta(days=30))
        estimate = self._estimate(self.product_a, self._make_model())
        self.assertAlmostEqual(estimate.adu, 37 / 61)

    def test_insufficient_stock_history_uses_calendar_with_warning(self):
        today = self._today()
        self._make_move(self.product_a, 34, today - timedelta(days=30),
                        outgoing=False)
        self._make_move(self.product_a, 34, today - timedelta(days=30))
        estimate = self._estimate(self.product_a, self._make_model())
        self.assertAlmostEqual(estimate.adu, 34 / 30)
        self.assertLessEqual(estimate.confidence, 0.2)
        self.assertTrue(any("insuficientes" in w for w in estimate.warnings))
        self.assertNotIn("Se descontaron", estimate.explanation)

    def test_invalid_inventory_does_not_inflate_sparse_sales(self):
        """Un saldo imposible no prueba que los días sin ventas fueran quiebres."""
        self._make_move(self.product_a, 10, self._today() - timedelta(days=30))
        self._set_stock(self.product_a, -100)
        estimate = self._estimate(self.product_a, self._make_model(
            weight_config="30:1.0", lookback_days=30, outlier_percentile=0))
        self.assertAlmostEqual(estimate.adu, 10 / 30)
        self.assertLessEqual(estimate.confidence, 0.2)
        self.assertTrue(any("stock" in warning.lower() for warning in estimate.warnings))

    def test_positive_current_stock_with_impossible_history_uses_calendar(self):
        self._make_move(self.product_a, 10, self._today() - timedelta(days=30))
        self._make_move(
            self.product_a, 100, self._today() - timedelta(days=1), outgoing=False)
        self._set_stock(self.product_a, 10)
        model = self._make_model(
            weight_config="30:1.0", lookback_days=30, outlier_percentile=0)
        estimate = self._estimate(self.product_a, model)
        self.assertAlmostEqual(estimate.adu, 10 / 30)
        self.assertLessEqual(estimate.confidence, 0.2)
        self.assertIn("calendario", estimate.explanation)

    # ------------------------------------------------------------------
    # Historia corta
    # ------------------------------------------------------------------
    def test_new_product_uses_only_the_windows_that_fit(self):
        self._sell_daily(self.product_a, 10, 16, 1)
        estimate = self._estimate(self.product_a, self._make_model())

        self.assertAlmostEqual(estimate.adu, 10.0, places=3)
        self.assertLessEqual(estimate.confidence, 0.2,
                             "15 días de historia no dan confianza")

    def test_product_without_history_returns_zero(self):
        estimate = self._estimate(self.product_a, self._make_model())
        self.assertAlmostEqual(estimate.adu, 0.0)
        self.assertAlmostEqual(estimate.confidence, 0.0)
        self.assertTrue(estimate.warnings)

    def test_few_moves_lower_confidence(self):
        today = self._today()
        for offset in range(1, 6):
            self._make_move(self.product_a, 10, today - timedelta(days=offset))
        estimate = self._estimate(self.product_a, self._make_model())
        self.assertLessEqual(estimate.confidence, 0.3)

    # ------------------------------------------------------------------
    # Outliers
    # ------------------------------------------------------------------
    def test_outlier_is_winsorized(self):
        """Una venta mayorista puntual no puede redefinir la demanda diaria.

        Una sola ventana, para que la comparación con el test siguiente aísle
        el recorte y no mezcle el efecto de la ponderación.
        """
        self._sell_daily(self.product_a, 10, 91, 1)
        self._make_move(self.product_a, 490, self._today() - timedelta(days=45))

        model = self._make_model(weight_config="90:1.0")
        estimate = self._estimate(self.product_a, model)
        self.assertAlmostEqual(estimate.adu, 10.0, places=3)
        self.assertAlmostEqual(estimate.sigma, 0.0, places=3)

    def test_outlier_without_winsorization(self):
        self._sell_daily(self.product_a, 10, 91, 1)
        self._make_move(self.product_a, 490, self._today() - timedelta(days=45))

        model = self._make_model(weight_config="90:1.0", outlier_percentile=0)
        estimate = self._estimate(self.product_a, model)
        self.assertAlmostEqual(estimate.adu, 1390 / 90, places=2)
        self.assertGreater(estimate.sigma, 40.0)

    def test_sparse_demand_is_not_zeroed_by_the_percentile(self):
        """Con demanda esporádica el percentil 95 cae en cero: no se recorta."""
        today = self._today()
        self._make_move(self.product_a, 300, today - timedelta(days=90),
                        outgoing=False)
        for offset in (70, 45, 20):
            self._make_move(self.product_a, 100, today - timedelta(days=offset))

        model = self._make_model(weight_config="90:1.0")
        estimate = self._estimate(self.product_a, model)
        self.assertGreater(estimate.adu, 0.0,
                           "Recortar a cero dejaría el producto sin demanda")
        # 300 unidades sobre los 71 días en que hubo algo que vender.
        self.assertAlmostEqual(estimate.adu, 300 / 71, places=2)

    # ------------------------------------------------------------------
    # Casos borde
    # ------------------------------------------------------------------
    def test_returns_never_produce_negative_demand(self):
        today = self._today()
        self._make_move(self.product_a, 5, today - timedelta(days=3))
        self._make_return(self.product_a, 20, today - timedelta(days=2))

        model = self._make_model(ignore_stockout_days=False, outlier_percentile=0)
        estimate = self._estimate(self.product_a, model)
        self.assertAlmostEqual(estimate.adu, 0.0)

    def test_explanation_is_readable(self):
        self._sell_daily(self.product_a, 10, 91, 31)
        estimate = self._estimate(self.product_a, self._make_model())
        self.assertIn("unidades por día", estimate.explanation)
        self.assertIn("días sin stock", estimate.explanation)

    # ------------------------------------------------------------------
    # Configuración del modelo
    # ------------------------------------------------------------------
    def test_weights_must_sum_to_one(self):
        with self.assertRaises(ValidationError):
            self._make_model(weight_config="14:0.5,30:0.3")

    def test_weight_windows_must_fit_the_lookback(self):
        with self.assertRaises(ValidationError):
            self._make_model(weight_config="14:0.5,30:0.5", lookback_days=20)

    def test_weight_config_format_is_validated(self):
        with self.assertRaises(ValidationError):
            self._make_model(weight_config="catorce dias")

    def test_service_level_is_bounded(self):
        with self.assertRaises(ValidationError):
            self._make_model(service_level=1.5)

    def test_z_value_interpolates(self):
        model = self._make_model(service_level=0.95)
        self.assertAlmostEqual(model._z_value(), 1.65, places=2)
        # El campo guarda 3 decimales, así que se interpola sobre un punto medio
        # que exista con esa precisión.
        model.service_level = 0.985
        self.assertAlmostEqual(model._z_value(), (2.05 + 2.33) / 2, places=2)

    def test_default_model_is_available(self):
        model = self.env["res.company"]._prometeo_default_demand_model()
        self.assertTrue(model, "El módulo trae un modelo por defecto")
        self.assertEqual(model.method, "weighted_ma")
