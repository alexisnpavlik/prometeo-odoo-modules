# -*- coding: utf-8 -*-
import logging
import math
import statistics

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang

from .datatypes import Estimate

_logger = logging.getLogger(__name__)

# Umbrales de confianza. La historia mínima no está acá porque es
# configurable por modelo (campo `min_history_days`).
CONFIDENCE_MIN_MOVES = 10

# Por debajo de esta cantidad de días la serie es demasiado corta para que un
# percentil signifique algo, y recortar haría más daño que el outlier.
MIN_VALUES_TO_WINSORIZE = 10
CONFIDENCE_MAX_STOCKOUT_RATIO = 0.5
CONFIDENCE_MAX_CV = 1.5

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
            "alpha": self.alpha,
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

    # ------------------------------------------------------------------
    # Estadística sin dependencias externas
    # ------------------------------------------------------------------
    def _outlier_cap(self, values):
        """Valor del percentil de recorte, o None si no corresponde recortar.

        Devuelve None cuando el percentil cae en cero, que es lo que pasa con
        demanda esporádica: un producto que vende 100 unidades una vez por mes
        tiene 87 días en cero sobre 90, y recortar a cero lo dejaría con
        demanda nula. El outlier molesta menos que eso.
        """
        self.ensure_one()
        percentile = self.outlier_percentile
        if not percentile or len(values) < MIN_VALUES_TO_WINSORIZE:
            return None
        ordered = sorted(values)
        index = int(math.ceil(percentile * len(ordered))) - 1
        index = min(max(index, 0), len(ordered) - 1)
        cap = ordered[index]
        return cap if cap > 0 else None

    def _winsorize(self, values, cap=None):
        """Recorta los valores por encima del tope.

        Una venta mayorista puntual de 500 unidades sobre una demanda de 10 por
        día no solo dispara el desvío: también triplica el promedio, y el
        sistema termina comprando para un cliente que no va a volver. Se recorta
        el pico y el resto de la serie queda intacta.
        """
        self.ensure_one()
        if cap is None:
            cap = self._outlier_cap(values)
        if cap is None:
            return list(values)
        return [min(value, cap) for value in values]

    def _stdev(self, values):
        """Desvío estándar muestral. Con menos de dos puntos no hay desvío."""
        if len(values) < 2:
            return 0.0
        return statistics.stdev(values)

    def _stockout_correction_enabled(self, series, product_id):
        """Un saldo imposible no demuestra que los días sin venta sean quiebres."""
        return (self.ignore_stockout_days
                and product_id not in series.unreliable_stock_ids)

    def _confidence(self, series, product_id, adu, sigma):
        """Qué tan confiable es la estimación, de 0 a 1.

        Se toma el mínimo de todas las penalizaciones que apliquen: alcanza con
        un solo problema serio para que la línea haya que mirarla a mano.
        """
        self.ensure_one()
        history = series.history_days(product_id)
        base = 0.8 + 0.2 * min(history / (self.lookback_days or 1), 1.0)
        scores = [min(base, 1.0)]
        if product_id in series.unreliable_stock_ids:
            scores.append(0.2)
        if history < self.min_history_days:
            scores.append(0.2)
        if series.moves(product_id) < CONFIDENCE_MIN_MOVES:
            scores.append(0.3)
        if series.stockout_ratio(product_id) > CONFIDENCE_MAX_STOCKOUT_RATIO:
            scores.append(0.4)
        if adu > 0 and (sigma / adu) > CONFIDENCE_MAX_CV:
            scores.append(0.5)
        return round(min(scores), 2)

    def _confidence_warnings(self, series, product_id, adu, sigma):
        """Por qué la confianza es baja, en texto.

        "Esta línea tiene poca confianza" no le sirve a nadie si no dice cuál
        de los cuatro problemas es: la acción del operador es distinta si le
        falta historia que si el producto estuvo agotado la mitad del tiempo.
        """
        self.ensure_one()
        warnings = []
        history = series.history_days(product_id)
        if history < self.min_history_days:
            warnings.append(_(
                "Solo %(days)s días de historia, por debajo de los %(minimum)s "
                "que pide el modelo.", days=history, minimum=self.min_history_days,
            ))
        moves = series.moves(product_id)
        if moves < CONFIDENCE_MIN_MOVES:
            warnings.append(_(
                "Apenas %(moves)s movimientos de salida en la ventana.", moves=moves,
            ))
        ratio = series.stockout_ratio(product_id)
        if product_id in series.unreliable_stock_ids:
            warnings.append(_(
                "Stock inconsistente: se estimaron ventas por día calendario, "
                "sin corrección por faltantes. Revisá el inventario; las ventas "
                "perdidas no se pueden cuantificar con estos datos."
            ))
        elif ratio > CONFIDENCE_MAX_STOCKOUT_RATIO:
            warnings.append(_(
                "Estuvo sin stock el %(pct)s%% de los días: la demanda real "
                "puede ser bastante mayor.", pct=round(ratio * 100),
            ))
        if adu > 0 and (sigma / adu) > CONFIDENCE_MAX_CV:
            warnings.append(_(
                "La venta diaria es muy irregular: el desvío supera vez y media "
                "al promedio."
            ))
        return warnings

    # ------------------------------------------------------------------
    # Explicación
    # ------------------------------------------------------------------
    def _format_number(self, value, digits=2):
        return formatLang(self.env, value, digits=digits)

    def _build_explanation(self, series, product_id, adu, windows):
        """Por qué salió ese número, en castellano y sin jerga."""
        self.ensure_one()
        window_txt = "/".join(str(days) for days, _weight in windows)
        parts = [_(
            "Vendés %(adu)s unidades por día (promedio ponderado de las ventanas "
            "de %(windows)s días).",
            adu=self._format_number(adu, digits=2), windows=window_txt,
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
        elif stockout:
            parts.append(_(
                "Hubo %(days)s días sin stock que igual cuentan como venta cero.",
                days=stockout,
            ))
        history = series.history_days(product_id)
        if history < self.lookback_days:
            parts.append(_(
                "Historia disponible: %(days)s días de los %(lookback)s pedidos.",
                days=history, lookback=self.lookback_days,
            ))
        if self.outlier_percentile:
            parts.append(_(
                "Los días por encima del percentil %(pct)s se recortaron.",
                pct=self._format_number(self.outlier_percentile * 100, digits=0),
            ))
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Estimadores
    # ------------------------------------------------------------------
    def _estimate_weighted_ma(self, series):
        """Promedio móvil ponderado de varias ventanas.

        Las ventanas cortas pesan más para que el modelo reaccione a un cambio
        de ritmo, y las largas amortiguan el ruido. Si un producto no tiene
        historia para una ventana, esa ventana se descarta y los pesos se
        renormalizan sobre las que quedan.
        """
        self.ensure_one()
        weights = self._parse_weight_config()
        result = {}
        for product_id in series.product_ids:
            result[product_id] = self._estimate_one_weighted_ma(
                series, product_id, weights)
        return result

    def _estimate_one_weighted_ma(self, series, product_id, weights):
        self.ensure_one()
        warnings = series.product_notes(product_id)
        history = series.history_days(product_id)
        if history <= 0:
            return Estimate(
                method_used="weighted_ma", confidence=0.0,
                explanation=_("El producto no tiene movimientos en el almacén."),
                warnings=warnings + [_("Sin historia en la ventana analizada.")],
            )
        if (self._stockout_correction_enabled(series, product_id)
                and series.days_with_stock(product_id) <= 0):
            return Estimate(
                method_used="weighted_ma", confidence=0.0,
                explanation=_(
                    "El producto estuvo sin stock toda la ventana: no hay demanda "
                    "observable para estimar."),
                warnings=warnings + [_("Sin stock en toda la ventana.")],
            )

        usable = [(days, weight) for days, weight in weights if days <= history]
        if not usable:
            # Producto nuevo: ninguna ventana entra en su historia. Se usa la
            # más corta sobre los días que sí existen.
            shortest = min(days for days, _weight in weights)
            usable = [(shortest, 1.0)]
            warnings.append(_(
                "Solo hay %(days)s días de historia: se estimó con la ventana "
                "más corta.", days=history,
            ))

        # El tope de recorte se calcula una sola vez sobre la ventana larga, y
        # se aplica igual en todas las ventanas: si cada una calculara su propio
        # percentil, el mismo día podría contar recortado en una y entero en otra.
        only_with_stock = self._stockout_correction_enabled(series, product_id)
        lookback_values = series.daily_values(
            product_id, days=self.lookback_days, only_with_stock=only_with_stock)
        cap = self._outlier_cap(lookback_values)
        sigma = self._stdev(self._winsorize(lookback_values, cap))

        # Una ventana sin días utilizables no aporta información: se descarta y
        # su peso se reparte entre las que sí la tienen. Dejarla valiendo cero
        # hundiría el promedio de un producto que estuvo agotado justo en la
        # ventana corta, que es el caso que más urge reponer.
        contributions = []
        for days, weight in usable:
            values = series.daily_values(
                product_id, days=days, only_with_stock=only_with_stock)
            if not values:
                continue
            rate = sum(self._winsorize(values, cap)) / len(values)
            contributions.append((days, weight, rate))

        if not contributions:
            return Estimate(
                method_used="weighted_ma", confidence=0.0,
                explanation=_(
                    "No hay ningún día con stock en las ventanas analizadas."),
                warnings=warnings + [_("Sin días utilizables para estimar.")],
            )
        if len(contributions) < len(usable):
            dropped = len(usable) - len(contributions)
            warnings.append(_(
                "Se descartaron %(count)s ventana(s) sin días con stock y se "
                "repartió su peso entre las restantes.", count=dropped,
            ))

        total_weight = sum(weight for _days, weight, _rate in contributions)
        if total_weight <= 0:
            total_weight = float(len(contributions))
            contributions = [(days, 1.0, rate) for days, _w, rate in contributions]

        adu = sum(
            rate * (weight / total_weight)
            for _days, weight, rate in contributions
        )
        # Las devoluciones pueden superar a las ventas en una ventana corta.
        # Demanda negativa no existe: es cero.
        adu = max(adu, 0.0)
        usable = [(days, weight) for days, weight, _rate in contributions]

        warnings += self._confidence_warnings(series, product_id, adu, sigma)
        return Estimate(
            adu=adu,
            sigma=sigma,
            confidence=self._confidence(series, product_id, adu, sigma),
            method_used="weighted_ma",
            explanation=self._build_explanation(series, product_id, adu, usable),
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Stock de seguridad
    # ------------------------------------------------------------------
    def _safety_stock(self, sigma, lead_time_days, adu):
        """Colchón para absorber la variabilidad durante el plazo de entrega.

        SS = Z x sigma x raíz(lead time). Con desvío cero se usa medio día de
        venta como piso: una demanda perfectamente constante casi siempre
        significa pocos datos, no estabilidad real, y dejar el colchón en cero
        garantiza quebrar ante el primer día raro.
        """
        self.ensure_one()
        if sigma <= 0:
            return max(adu, 0.0) * 0.5
        return self._z_value() * sigma * math.sqrt(max(lead_time_days, 0.0))
