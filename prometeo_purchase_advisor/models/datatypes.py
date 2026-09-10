# -*- coding: utf-8 -*-
"""Contratos de datos del pipeline de estimación.

Son clases planas, no modelos de Odoo: viven en memoria durante una corrida y
son el único acoplamiento entre la lectura de movimientos y los estimadores.
Un estimador nuevo consume `DemandSeries` y produce `Estimate`, sin tocar nada
más del pipeline.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class DemandSeries:
    """Serie de demanda ya materializada. Se construye una sola vez por corrida.

    La ventana es [date_from, date_to), con date_to exclusivo.

    Los días se guardan de forma dispersa: `qty` solo tiene los días con
    movimiento y `stockout_days` solo los días sin stock. Guardar un valor por
    producto y por día sería del orden de dos millones de entradas para 20k
    productos y 90 días; disperso son unas decenas de miles.
    """

    warehouse_id: int
    date_from: date
    date_to: date
    product_ids: list = field(default_factory=list)
    qty: dict = field(default_factory=dict)              # {product_id: {date: qty neta}}
    stockout_days: dict = field(default_factory=dict)    # {product_id: set(date)}
    first_move_date: dict = field(default_factory=dict)  # {product_id: date}
    move_count: dict = field(default_factory=dict)       # {product_id: int}
    notes: dict = field(default_factory=dict)            # {product_id: [str]}
    unreliable_stock_ids: set = field(default_factory=set)

    # ------------------------------------------------------------------
    # Ventanas
    # ------------------------------------------------------------------
    @property
    def window_days(self):
        return max((self.date_to - self.date_from).days, 0)

    def _window_start(self, days=None):
        """Inicio de la sub-ventana de los últimos `days` días, acotada a la serie."""
        if not days:
            return self.date_from
        return max(self.date_to - timedelta(days=days), self.date_from)

    def _effective_start(self, product_id, days=None):
        """Inicio real para este producto.

        Los días anteriores al primer movimiento no son demanda cero: el
        producto no existía todavía en el almacén. Contarlos hundiría el
        promedio de cualquier alta reciente.
        """
        start = self._window_start(days)
        first = self.first_move_date.get(product_id)
        if first and first > start:
            return first
        return start

    def countable_days(self, product_id, days=None):
        """Días de la ventana en los que el producto ya existía en el almacén."""
        start = self._effective_start(product_id, days)
        return max((self.date_to - start).days, 0)

    def history_days(self, product_id):
        """Cuántos días de historia utilizable tiene el producto."""
        return self.countable_days(product_id)

    # ------------------------------------------------------------------
    # Demanda
    # ------------------------------------------------------------------
    def total_qty(self, product_id, days=None):
        """Demanda neta (ventas menos devoluciones) de la sub-ventana."""
        start = self._effective_start(product_id, days)
        per_day = self.qty.get(product_id) or {}
        return sum(
            qty for day, qty in per_day.items()
            if start <= day < self.date_to
        )

    def daily_values(self, product_id, days=None, only_with_stock=False):
        """Serie diaria de demanda, un valor por día de la sub-ventana.

        Con `only_with_stock` se saltean los días sin stock, para que el desvío
        se calcule sobre la misma base que el promedio.
        """
        start = self._effective_start(product_id, days)
        per_day = self.qty.get(product_id) or {}
        missing = self.stockout_days.get(product_id) or set()
        values = []
        day = start
        while day < self.date_to:
            if not (only_with_stock and day in missing):
                values.append(per_day.get(day, 0.0))
            day += timedelta(days=1)
        return values

    # ------------------------------------------------------------------
    # Disponibilidad
    # ------------------------------------------------------------------
    def days_with_stock(self, product_id, days=None):
        """Días de la ventana en los que el producto estuvo disponible."""
        total = self.countable_days(product_id, days)
        if not total:
            return 0
        start = self._effective_start(product_id, days)
        missing = self.stockout_days.get(product_id) or set()
        without = sum(1 for day in missing if start <= day < self.date_to)
        return max(total - without, 0)

    def stockout_ratio(self, product_id, days=None):
        """Proporción de días sin stock, de 0 a 1."""
        total = self.countable_days(product_id, days)
        if not total:
            return 0.0
        return 1.0 - (self.days_with_stock(product_id, days) / total)

    def moves(self, product_id):
        """Cantidad de movimientos de salida del producto en la ventana."""
        return self.move_count.get(product_id, 0)

    def product_notes(self, product_id):
        return list(self.notes.get(product_id) or [])

    def add_note(self, product_id, message):
        self.notes.setdefault(product_id, []).append(message)


@dataclass
class Estimate:
    """Salida de un estimador. Contrato estable entre métodos.

    `method_used` puede diferir del método pedido: un estimador que no puede
    correr con los datos disponibles degrada al fallback y lo deja asentado acá
    en vez de fallar o inventar un número.
    """

    adu: float = 0.0
    sigma: float = 0.0
    confidence: float = 0.0
    method_used: str = ""
    explanation: str = ""
    warnings: list = field(default_factory=list)
    observed_sales: dict = field(default_factory=dict)
