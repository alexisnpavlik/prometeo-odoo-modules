# -*- coding: utf-8 -*-
import logging
import math
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Ventana sobre la que se clasifica. Medio año amortigua la estacionalidad
# corta sin arrastrar productos que ya salieron del surtido.
CLASSIFICATION_WINDOW_DAYS = 180

# Cortes acumulados de la clasificación ABC.
ABC_A_THRESHOLD = 0.80
ABC_B_THRESHOLD = 0.95

# Cortes del coeficiente de variación para XYZ.
XYZ_X_THRESHOLD = 0.5
XYZ_Y_THRESHOLD = 1.0

ABC_SELECTION = [("a", "A"), ("b", "B"), ("c", "C")]
XYZ_SELECTION = [("x", "X"), ("y", "Y"), ("z", "Z")]


class ProductCategory(models.Model):
    _inherit = "product.category"

    demand_model_id = fields.Many2one(
        "prometeo.demand.model", string="Modelo de demanda",
        help="Modelo usado para los productos de esta categoría, salvo que el "
             "producto tenga uno propio.",
    )


class ProductTemplate(models.Model):
    _inherit = "product.template"

    demand_model_id = fields.Many2one(
        "prometeo.demand.model", string="Modelo de demanda",
        help="Fuerza un modelo de estimación para este producto, por encima de "
             "la categoría y de las reglas.",
    )
    exclude_from_suggestion = fields.Boolean(
        string="Excluir del recomendador",
        help="El producto no aparece en las sugerencias de compra.",
    )


class ProductProduct(models.Model):
    _inherit = "product.product"

    # Escritas por el cron semanal de clasificación, no en cada sugerencia:
    # recalcularlas por corrida sería caro y las clases no cambian a diario.
    abc_class = fields.Selection(
        ABC_SELECTION, string="Clase ABC", readonly=True, index=True,
        help="Contribución al margen de los últimos 180 días. "
             "A: primeros 80%. B: hasta 95%. C: el resto.",
    )
    xyz_class = fields.Selection(
        XYZ_SELECTION, string="Clase XYZ", readonly=True, index=True,
        help="Variabilidad de la demanda. X: estable. Y: variable. Z: errática.",
    )
    abc_xyz_date = fields.Datetime(
        string="Clasificado el", readonly=True,
        help="Última vez que el cron recalculó las clases ABC/XYZ.",
    )

    # ------------------------------------------------------------------
    # Clasificación
    # ------------------------------------------------------------------
    @api.model
    def _classification_stats(self, company, since):
        """{product_id: (unidades vendidas, suma de cuadrados, días con venta)}.

        Se agrega disperso y el desvío se reconstruye después con la identidad
        var = (sumaCuadrados - n x media^2) / (n-1). Así el denominador puede
        ser la ventana completa sin tener que rellenar en SQL los días en cero,
        que en retail son la mayoría.
        """
        self.env.flush_all()
        self.env.cr.execute("""
            WITH daily AS (
                SELECT sm.product_id,
                       (sm.date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS d,
                       SUM(sm.product_qty) AS qty
                  FROM stock_move sm
                  JOIN stock_location src  ON src.id  = sm.location_id
                  JOIN stock_location dest ON dest.id = sm.location_dest_id
                 WHERE sm.state = 'done'
                   AND sm.company_id = %(company_id)s
                   AND dest.usage = 'customer'
                   AND src.usage = 'internal'
                   AND sm.date >= %(since)s
                 GROUP BY 1, 2
            )
            SELECT product_id, SUM(qty), SUM(qty * qty), COUNT(*)
              FROM daily
             GROUP BY product_id
        """, {
            "tz": self.env["prometeo.demand.series.builder"]._timezone(),
            "company_id": company.id,
            "since": since,
        })
        return {
            row[0]: (float(row[1] or 0.0), float(row[2] or 0.0), int(row[3] or 0))
            for row in self.env.cr.fetchall()
        }

    @api.model
    def _coefficient_of_variation(self, total, sumsq, days):
        """Variabilidad relativa de la demanda diaria."""
        if days < 2 or total <= 0:
            return None
        mean = total / days
        variance = (sumsq - days * mean * mean) / (days - 1)
        if variance <= 0:
            return 0.0
        return math.sqrt(variance) / mean

    def _classify_for_company(self, company):
        """Escribe las clases ABC y XYZ de los productos de esa compañía."""
        since = fields.Datetime.now() - timedelta(days=CLASSIFICATION_WINDOW_DAYS)
        stats = self._classification_stats(company, since)
        products = self.with_company(company).with_context(active_test=False).search([
            ("is_storable", "=", True),
            ("company_id", "in", [False, company.id]),
        ])

        # ABC por valor de consumo: unidades por costo. El margen real vive en
        # las líneas de venta, que este módulo no lee por decisión de diseño, y
        # el precio de lista de esta base es de relleno.
        valued = []
        for product in products:
            total, _sumsq, _days = stats.get(product.id, (0.0, 0.0, 0))
            valued.append((product, total * (product.standard_price or 0.0)))
        total_value = sum(value for _product, value in valued)
        valued.sort(key=lambda item: -item[1])

        now = fields.Datetime.now()
        cumulative = 0.0
        for product, value in valued:
            if total_value > 0:
                # La clase se decide con lo acumulado ANTES de sumar este
                # producto: el que cruza el corte todavía pertenece a la clase
                # alta. Mirándolo después, un producto que solo por sí mismo
                # supera el 80% quedaría fuera de A, y no habría ningún A.
                previous = cumulative
                cumulative += value / total_value
                if previous < ABC_A_THRESHOLD:
                    abc = "a"
                elif previous < ABC_B_THRESHOLD:
                    abc = "b"
                else:
                    abc = "c"
            else:
                abc = "c"

            total, sumsq, _days_sold = stats.get(product.id, (0.0, 0.0, 0))
            cv = self._coefficient_of_variation(
                total, sumsq, CLASSIFICATION_WINDOW_DAYS)
            if cv is None:
                xyz = "z"
            elif cv < XYZ_X_THRESHOLD:
                xyz = "x"
            elif cv < XYZ_Y_THRESHOLD:
                xyz = "y"
            else:
                xyz = "z"

            if product.abc_class != abc or product.xyz_class != xyz:
                product.write({"abc_class": abc, "xyz_class": xyz,
                               "abc_xyz_date": now})
            else:
                product.abc_xyz_date = now
        _logger.info("Clasificados %s productos de %s", len(products), company.name)
        return True

    @api.model
    def _cron_classify_products(self):
        for company in self.env["res.company"].search([]):
            self._classify_for_company(company)
        return True
