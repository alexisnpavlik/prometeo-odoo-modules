# -*- coding: utf-8 -*-
"""Lectura de movimientos de stock → DemandSeries.

Todo el trabajo pesado va en SQL. El objetivo es que 20k productos por almacén
entren en una corrida sin timeout, y eso descarta recorrer el ORM producto por
producto.
"""
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, models

_logger = logging.getLogger(__name__)

# Tolerancia al reconstruir stock hacia atrás: por debajo de esto un saldo
# negativo es ruido de redondeo, no un dato inconsistente.
NEGATIVE_STOCK_TOLERANCE = 0.001


class PrometeoDemandSeriesBuilder(models.AbstractModel):
    _name = "prometeo.demand.series.builder"
    _description = "Constructor de series de demanda"

    # ------------------------------------------------------------------
    # Helpers de zona horaria
    # ------------------------------------------------------------------
    def _timezone(self):
        """Zona en la que se agrupan los días.

        Los movimientos se guardan en UTC. Agrupar por día UTC en Argentina
        manda las ventas de después de las 21 al día siguiente, que es
        exactamente el horario pico de un local.
        """
        return self.env.user.tz or self.env.company.partner_id.tz or "UTC"

    def _to_utc(self, day, tz_name):
        """Convierte el comienzo de un día local al timestamp UTC equivalente."""
        tz = pytz.timezone(tz_name)
        local = tz.localize(datetime.combine(day, time.min))
        return local.astimezone(pytz.UTC).replace(tzinfo=None)

    def _today(self, tz_name):
        return datetime.now(pytz.timezone(tz_name)).date()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    @api.model
    def build(self, warehouse, product_ids, date_from, date_to):
        """Arma la serie de demanda de esos productos en ese almacén.

        `date_to` es exclusivo. Devuelve un DemandSeries listo para el estimador.
        """
        from .datatypes import DemandSeries

        product_ids = list(product_ids)
        series = DemandSeries(
            warehouse_id=warehouse.id,
            date_from=date_from,
            date_to=date_to,
            product_ids=product_ids,
        )
        if not product_ids or date_to <= date_from:
            return series

        # El SQL crudo no ve lo que el ORM todavía tiene en su buffer. Si la
        # corrida sigue a cualquier escritura de la misma transacción (una
        # validación de albarán, un ajuste), sin esto lee datos viejos.
        self.env.flush_all()

        warehouse.check_access("read")

        tz_name = self._timezone()
        wh_path = (warehouse.view_location_id.parent_path or "") + "%"
        params = {
            "company_id": warehouse.company_id.id,
            "product_ids": product_ids,
            "wh_path": wh_path,
            "tz": tz_name,
            "date_from": self._to_utc(date_from, tz_name),
            "date_to": self._to_utc(date_to, tz_name),
        }

        self._fill_demand(series, params)
        self._fill_first_move_date(series, params, tz_name)
        self._fill_stockout_days(series, warehouse, params, tz_name)
        return series

    # ------------------------------------------------------------------
    # Demanda: salidas a cliente, netas de devoluciones
    # ------------------------------------------------------------------
    def _fill_demand(self, series, params):
        """Demanda diaria neta por producto.

        Una devolución del cliente resta: sin eso, un producto que se vende y se
        devuelve todo el tiempo parece un éxito de ventas.
        """
        self.env.cr.execute("""
            SELECT sm.product_id,
                   (sm.date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS move_date,
                   SUM(CASE WHEN dest.usage = 'customer'
                            THEN sm.product_qty ELSE -sm.product_qty END) AS qty,
                   COUNT(*) FILTER (WHERE dest.usage = 'customer') AS moves
              FROM stock_move sm
              JOIN stock_location src  ON src.id  = sm.location_id
              JOIN stock_location dest ON dest.id = sm.location_dest_id
              LEFT JOIN stock_picking picking ON picking.id = sm.picking_id
             WHERE sm.state = 'done'
               AND sm.company_id = %(company_id)s
               AND sm.product_id = ANY(%(product_ids)s)
               AND sm.date >= %(date_from)s
               AND sm.date <  %(date_to)s
               AND NOT EXISTS (
                   SELECT 1 FROM res_company company
                    WHERE company.partner_id = COALESCE(picking.partner_id, sm.partner_id)
               )
               AND (
                     (dest.usage = 'customer' AND src.usage = 'internal'
                      AND src.parent_path LIKE %(wh_path)s)
                  OR (src.usage = 'customer' AND dest.usage = 'internal'
                      AND dest.parent_path LIKE %(wh_path)s)
                   )
             GROUP BY sm.product_id, 2
        """, params)
        for product_id, move_date, qty, moves in self.env.cr.fetchall():
            series.qty.setdefault(product_id, {})[move_date] = float(qty or 0.0)
            series.move_count[product_id] = series.move_count.get(product_id, 0) + (moves or 0)

    # ------------------------------------------------------------------
    # Primer movimiento: desde cuándo el producto existe en el almacén
    # ------------------------------------------------------------------
    def _fill_first_move_date(self, series, params, tz_name):
        """Fecha del primer movimiento del producto en el almacén.

        Sin límite inferior a propósito: si el producto ya se movía antes de la
        ventana, toda la ventana cuenta como historia.
        """
        self.env.cr.execute("""
            SELECT sm.product_id,
                   MIN((sm.date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date) AS first_date
              FROM stock_move sm
              JOIN stock_location src  ON src.id  = sm.location_id
              JOIN stock_location dest ON dest.id = sm.location_dest_id
             WHERE sm.state = 'done'
               AND sm.company_id = %(company_id)s
               AND sm.product_id = ANY(%(product_ids)s)
               AND sm.date < %(date_to)s
               AND (src.parent_path LIKE %(wh_path)s
                    OR dest.parent_path LIKE %(wh_path)s)
             GROUP BY sm.product_id
        """, params)
        for product_id, first_date in self.env.cr.fetchall():
            series.first_move_date[product_id] = first_date

    # ------------------------------------------------------------------
    # Reconstrucción de disponibilidad
    # ------------------------------------------------------------------
    def _fill_stockout_days(self, series, warehouse, params, tz_name):
        """Marca los días en que el producto estuvo agotado.

        Es la pieza que evita que el módulo se muerda la cola: sin ella, un
        producto que se agota rápido registra días de venta cero, baja su
        promedio, y el sistema recomienda comprar todavía menos.

        Se reconstruye el stock hacia atrás desde el disponible actual, restando
        el neto de movimientos de cada día.
        """
        today = self._today(tz_name)
        recon_params = dict(params, recon_to=self._to_utc(
            today + timedelta(days=1), tz_name))

        self.env.cr.execute("""
            SELECT sm.product_id,
                   (sm.date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS move_date,
                   SUM(CASE
                         WHEN dest.usage = 'internal' AND dest.parent_path LIKE %(wh_path)s
                              AND NOT (src.usage = 'internal' AND src.parent_path LIKE %(wh_path)s)
                              THEN sm.product_qty
                         WHEN src.usage = 'internal' AND src.parent_path LIKE %(wh_path)s
                              AND NOT (dest.usage = 'internal' AND dest.parent_path LIKE %(wh_path)s)
                              THEN -sm.product_qty
                         ELSE 0 END) AS net,
                   SUM(CASE
                         WHEN src.usage = 'internal' AND src.parent_path LIKE %(wh_path)s
                              AND NOT (dest.usage = 'internal' AND dest.parent_path LIKE %(wh_path)s)
                              THEN sm.product_qty
                         ELSE 0 END) AS outbound
              FROM stock_move sm
              JOIN stock_location src  ON src.id  = sm.location_id
              JOIN stock_location dest ON dest.id = sm.location_dest_id
             WHERE sm.state = 'done'
               AND sm.company_id = %(company_id)s
               AND sm.product_id = ANY(%(product_ids)s)
               AND sm.date >= %(date_from)s
               AND sm.date <  %(recon_to)s
             GROUP BY sm.product_id, 2
        """, recon_params)
        net = {}
        outbound = {}
        for product_id, move_date, day_net, day_out in self.env.cr.fetchall():
            net.setdefault(product_id, {})[move_date] = float(day_net or 0.0)
            outbound.setdefault(product_id, {})[move_date] = float(day_out or 0.0)

        on_hand = self._current_qty(warehouse, series.product_ids)
        for product_id in series.product_ids:
            self._reconstruct_product(
                series, product_id, on_hand.get(product_id, 0.0),
                net.get(product_id, {}), outbound.get(product_id, {}), today,
            )

    def _current_qty(self, warehouse, product_ids):
        """Stock disponible actual de cada producto en el almacén."""
        products = self.env["product.product"].browse(product_ids).exists()
        products = products.with_context(warehouse_id=warehouse.id)
        return {p.id: p.qty_available for p in products}

    def _reconstruct_product(self, series, product_id, qty_now, net, outbound, today):
        """Camina hacia atrás desde hoy marcando los días sin stock."""
        missing = set()
        running = qty_now
        day = today
        clamped = qty_now < -NEGATIVE_STOCK_TOLERANCE
        while day >= series.date_from:
            had_stock = running > 0 or outbound.get(day, 0.0) > 0
            if not had_stock and series.date_from <= day < series.date_to:
                missing.add(day)
            running -= net.get(day, 0.0)
            if running < -NEGATIVE_STOCK_TOLERANCE:
                # Ajustes de inventario y datos viejos pueden dar saldos
                # imposibles. Se acota a cero y se avisa, en vez de arrastrar
                # el error hacia atrás por toda la ventana.
                clamped = True
                running = 0.0
            day -= timedelta(days=1)
        if missing:
            series.stockout_days[product_id] = missing
        if clamped:
            series.unreliable_stock_ids.add(product_id)
            series.add_note(product_id, (
                "La reconstrucción de stock dio saldos negativos: no permite "
                "identificar con fiabilidad los días sin stock."
            ))
