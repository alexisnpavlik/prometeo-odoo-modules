# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Cuantiles de la normal estándar. Se hardcodea para no depender de scipy.
Z_TABLE = {
    0.50: 0.00, 0.75: 0.67, 0.80: 0.84, 0.85: 1.04, 0.90: 1.28,
    0.925: 1.44, 0.95: 1.65, 0.975: 1.96, 0.98: 2.05, 0.99: 2.33, 0.995: 2.58,
}


class PrometeoDemandModel(models.Model):
    _name = "prometeo.demand.model"
    _description = "Modelo de estimación de demanda"
    _order = "sequence, id"

    name = fields.Char(string="Nombre", required=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one(
        "res.company", string="Compañía",
        default=lambda self: self.env.company,
    )
    method = fields.Selection(
        selection="_selection_method", string="Método", required=True,
        default="weighted_ma",
        help="Algoritmo usado para estimar la demanda diaria promedio.",
    )
    lookback_days = fields.Integer(
        string="Ventana de historia (días)", default=90,
        help="Cuántos días de movimientos se leen para estimar.",
    )
    service_level = fields.Float(
        string="Nivel de servicio", default=0.95, digits=(3, 3),
        help="Probabilidad objetivo de no quebrar durante el lead time. "
             "Determina el multiplicador Z del stock de seguridad.",
    )
    ignore_stockout_days = fields.Boolean(
        string="Ignorar días sin stock", default=True,
        help="No cuenta como demanda cero los días en que el producto estuvo "
             "agotado. Sin esto el sistema deja de comprar lo que más se vende.",
    )
    outlier_percentile = fields.Float(
        string="Percentil de recorte", default=0.95, digits=(3, 3),
        help="Las ventas diarias por encima de este percentil se recortan a su "
             "valor, para que una venta mayorista puntual no distorsione el "
             "promedio. 0 desactiva el recorte.",
    )
    min_history_days = fields.Integer(
        string="Historia mínima (días)", default=21,
        help="Por debajo de este umbral la estimación se marca como de baja confianza.",
    )
    weight_config = fields.Char(
        string="Pesos por ventana", default="14:0.5,30:0.3,90:0.2",
        help="Solo para promedio móvil ponderado. Formato 'días:peso' separados "
             "por coma. Los pesos deben sumar 1.",
    )
    alpha = fields.Float(
        string="Alpha", default=0.3, digits=(3, 3),
        help="Factor de suavizado, solo para métodos exponenciales.",
    )

    @api.model
    def _selection_method(self):
        """Métodos disponibles. Un módulo satélite extiende esta lista vía super()."""
        return [("weighted_ma", "Promedio móvil ponderado")]

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------
    @api.constrains("weight_config", "method", "lookback_days")
    def _check_weight_config(self):
        """Los pesos deben parsear y sumar 1, y caber en la ventana de historia."""
        for model in self:
            if model.method != "weighted_ma":
                continue
            weights = model._parse_weight_config()
            total = sum(w for _days, w in weights)
            if abs(total - 1.0) > 0.01:
                raise ValidationError(_(
                    "Los pesos de '%(name)s' suman %(total).2f. Deben sumar 1.",
                    name=model.name, total=total,
                ))
            largest = max(days for days, _w in weights)
            if model.lookback_days < largest:
                raise ValidationError(_(
                    "La ventana de historia (%(lookback)s días) es menor que la "
                    "ventana más grande de los pesos (%(largest)s días).",
                    lookback=model.lookback_days, largest=largest,
                ))

    @api.constrains("service_level")
    def _check_service_level(self):
        for model in self:
            if not 0.5 <= model.service_level <= 0.999:
                raise ValidationError(_(
                    "El nivel de servicio debe estar entre 0,5 y 0,999."
                ))

    @api.constrains("outlier_percentile")
    def _check_outlier_percentile(self):
        for model in self:
            if model.outlier_percentile and not 0.5 <= model.outlier_percentile <= 1.0:
                raise ValidationError(_(
                    "El percentil de recorte debe ser 0 (desactivado) o estar "
                    "entre 0,5 y 1."
                ))

    @api.constrains("lookback_days", "min_history_days")
    def _check_positive_days(self):
        for model in self:
            if model.lookback_days < 1:
                raise ValidationError(_("La ventana de historia debe ser de al menos 1 día."))
            if model.min_history_days < 0:
                raise ValidationError(_("La historia mínima no puede ser negativa."))

    # ------------------------------------------------------------------
    # Helpers de configuración
    # ------------------------------------------------------------------
    def _parse_weight_config(self):
        """Parsea 'weight_config' a [(días, peso), ...] ordenado por días.

        Levanta ValidationError con el texto original si el formato no es válido:
        el usuario tiene que poder ver qué escribió mal.
        """
        self.ensure_one()
        raw = (self.weight_config or "").strip()
        if not raw:
            raise ValidationError(_("Los pesos por ventana no pueden estar vacíos."))
        pairs = []
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ":" not in chunk:
                raise ValidationError(_(
                    "Formato de pesos inválido en '%(chunk)s'. Se espera 'días:peso'.",
                    chunk=chunk,
                ))
            days_txt, weight_txt = chunk.split(":", 1)
            try:
                days = int(days_txt.strip())
                weight = float(weight_txt.strip())
            except ValueError:
                raise ValidationError(_(
                    "Formato de pesos inválido en '%(chunk)s'. Se espera 'días:peso' "
                    "con días entero y peso decimal.",
                    chunk=chunk,
                ))
            if days < 1:
                raise ValidationError(_("Una ventana de pesos debe ser de al menos 1 día."))
            if weight < 0:
                raise ValidationError(_("Los pesos no pueden ser negativos."))
            pairs.append((days, weight))
        if not pairs:
            raise ValidationError(_("Los pesos por ventana no pueden estar vacíos."))
        return sorted(pairs)

    def _z_value(self):
        """Multiplicador Z del nivel de servicio, interpolado linealmente."""
        self.ensure_one()
        level = self.service_level
        keys = sorted(Z_TABLE)
        if level <= keys[0]:
            return Z_TABLE[keys[0]]
        if level >= keys[-1]:
            return Z_TABLE[keys[-1]]
        for low, high in zip(keys, keys[1:]):
            if low <= level <= high:
                span = high - low
                ratio = (level - low) / span if span else 0.0
                return Z_TABLE[low] + ratio * (Z_TABLE[high] - Z_TABLE[low])
        return Z_TABLE[keys[-1]]

    def _params_snapshot(self):
        """Parámetros exactos usados en una corrida, para trazabilidad."""
        self.ensure_one()
        return {
            "model_id": self.id,
            "model_name": self.name,
            "method": self.method,
            "lookback_days": self.lookback_days,
            "service_level": self.service_level,
            "ignore_stockout_days": self.ignore_stockout_days,
            "outlier_percentile": self.outlier_percentile,
            "min_history_days": self.min_history_days,
            "weight_config": self.weight_config,
        }

    # ------------------------------------------------------------------
    # Punto de entrada del estimador
    # ------------------------------------------------------------------
    def estimate(self, series):
        """Estima la demanda de cada producto de la serie.

        Despacha a `_estimate_<method>` por convención de nombre, igual que
        `delivery.carrier`. Devuelve {product_id: Estimate}.
        """
        self.ensure_one()
        method_fn = getattr(self, "_estimate_%s" % self.method, None)
        if method_fn is None:
            raise UserError(_(
                "El modelo de demanda '%(name)s' usa el método '%(method)s', que "
                "no está implementado. Puede faltar instalar el módulo que lo "
                "provee.",
                name=self.name, method=self.method,
            ))
        return method_fn(series)
