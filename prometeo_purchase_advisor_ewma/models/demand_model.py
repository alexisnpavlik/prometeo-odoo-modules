# -*- coding: utf-8 -*-
"""Estimador EWMA como extensión del recomendador.

El módulo base despacha a `_estimate_<method>` por convención de nombre, igual
que `delivery.carrier`. Agregar un método es extender el Selection y definir
ese método: no hace falta tocar ninguna otra etapa del pipeline.
"""
import logging

from odoo import _, api, models

from odoo.addons.prometeo_purchase_advisor.models.datatypes import Estimate

_logger = logging.getLogger(__name__)

# Con menos días que esto el suavizado no llega a estabilizarse y devuelve
# prácticamente el último valor observado.
MIN_POINTS_FOR_EWMA = 7


class PrometeoDemandModel(models.Model):
    _inherit = "prometeo.demand.model"

    @api.model
    def _selection_method(self):
        return super()._selection_method() + [
            ("ewma", "Suavizado exponencial (EWMA)"),
        ]

    def _estimate_ewma(self, series):
        """Promedio móvil exponencialmente ponderado."""
        self.ensure_one()
        alpha = min(max(self.alpha or 0.3, 0.01), 1.0)
        fallback_weights = self._parse_weight_config()
        return {
            product_id: self._estimate_one_ewma(
                series, product_id, alpha, fallback_weights)
            for product_id in series.product_ids
        }

    def _estimate_one_ewma(self, series, product_id, alpha, fallback_weights):
        self.ensure_one()
        only_with_stock = self._stockout_correction_enabled(series, product_id)
        values = series.daily_values(
            product_id, days=self.lookback_days, only_with_stock=only_with_stock)

        if len(values) < MIN_POINTS_FOR_EWMA:
            # Degradar, no fallar ni inventar: el contrato dice que el método
            # realmente usado vuelve en `method_used`.
            estimate = self._estimate_one_weighted_ma(
                series, product_id, fallback_weights)
            estimate.warnings.append(_(
                "Hay solo %(days)s días utilizables, menos de los %(minimum)s que "
                "necesita el suavizado exponencial: se estimó con el promedio "
                "ponderado.", days=len(values), minimum=MIN_POINTS_FOR_EWMA,
            ))
            return estimate

        cap = self._outlier_cap(values)
        capped = self._winsorize(values, cap)
        # daily_values viene del día más viejo al más nuevo, así que el último
        # valor es el que más pesa.
        level = capped[0]
        for value in capped[1:]:
            level = alpha * value + (1.0 - alpha) * level
        adu = max(level, 0.0)
        sigma = self._stdev(capped)

        warnings = series.product_notes(product_id)
        warnings += self._confidence_warnings(series, product_id, adu, sigma)
        return Estimate(
            adu=adu,
            sigma=sigma,
            confidence=self._confidence(series, product_id, adu, sigma),
            method_used="ewma",
            explanation=self._build_ewma_explanation(
                series, product_id, adu, alpha, len(capped)),
            warnings=warnings,
        )

    def _build_ewma_explanation(self, series, product_id, adu, alpha, points):
        self.ensure_one()
        parts = [_(
            "Vendés %(adu)s unidades por día (suavizado exponencial sobre "
            "%(points)s días, con alpha %(alpha)s: cuanto más reciente el día, "
            "más pesa).",
            adu=self._format_number(adu, digits=2), points=points,
            alpha=self._format_number(alpha, digits=2),
        )]
        stockout = len(series.stockout_days.get(product_id) or ())
        if product_id in series.unreliable_stock_ids:
            parts.append(_(
                "Se usaron días calendario porque el stock reconstruido es "
                "inconsistente. La estimación refleja ventas registradas."
            ))
        elif stockout and self._stockout_correction_enabled(series, product_id):
            parts.append(_(
                "Se descontaron %(days)s días sin stock del cálculo.", days=stockout,
            ))
        if self.outlier_percentile:
            parts.append(_(
                "Los días por encima del percentil %(pct)s se recortaron.",
                pct=self._format_number(self.outlier_percentile * 100, digits=0),
            ))
        return " ".join(parts)
