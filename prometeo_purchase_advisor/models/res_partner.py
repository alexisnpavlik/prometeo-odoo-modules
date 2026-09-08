# -*- coding: utf-8 -*-
"""Métricas de proveedor medidas sobre compras reales.

El plazo de entrega cargado a mano en `product.supplierinfo.delay` casi nunca
se actualiza. Lo que sí es verdad es cuánto tardó cada orden en llegar.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Ventana de compras que se mira para medir al proveedor.
MEASUREMENT_WINDOW_DAYS = 365
# Con menos órdenes que esto el promedio no significa nada.
MIN_SAMPLE_SIZE = 3
# Por debajo de un día no es un plazo de entrega: es que la orden se carga
# cuando la mercadería ya llegó. Medirlo así da cero y hace desaparecer el
# stock de seguridad, que se calcula sobre la raíz del plazo.
MIN_MEASURABLE_LEAD_TIME_DAYS = 1.0
# Último recurso cuando el proveedor no tiene historia ni plazo configurado.
FALLBACK_LEAD_TIME_DAYS = 7.0


class ResPartner(models.Model):
    _inherit = "res.partner"

    measured_lead_time = fields.Float(
        string="Plazo medido (días)", readonly=True, digits=(16, 1),
        help="Promedio real entre la confirmación de la orden y la primera "
             "recepción, sobre el último año de compras.",
    )
    lead_time_sample_size = fields.Integer(
        string="Órdenes medidas", readonly=True,
        help="Cuántas órdenes entraron en el promedio del plazo.",
    )
    fill_rate = fields.Float(
        string="Nivel de cumplimiento", readonly=True, digits=(3, 2),
        help="Proporción de lo pedido que el proveedor efectivamente entregó, "
             "sobre el último año.",
    )
    metrics_date = fields.Datetime(string="Métricas calculadas el", readonly=True)

    # ------------------------------------------------------------------
    # Medición
    # ------------------------------------------------------------------
    def _measure_lead_times(self):
        """{partner_id: (días, tamaño de muestra)} sobre compras reales.

        Se mide contra la primera recepción de cada orden, no la última: para
        reponer lo que importa es cuándo empezó a haber mercadería.

        El picking no se puede unir a la orden por `purchase_id`: ese campo es
        un related sin almacenar, no existe como columna. Se pasa por el
        movimiento, que sí guarda la línea de compra que lo originó.
        """
        if not self:
            return {}
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT po.partner_id,
                   AVG(EXTRACT(EPOCH FROM (r.first_done - po.date_approve)) / 86400.0)
                       AS lead_days,
                   COUNT(*) AS sample_size
              FROM purchase_order po
              JOIN (
                    SELECT pol.order_id, MIN(sp.date_done) AS first_done
                      FROM purchase_order_line pol
                      JOIN stock_move sm ON sm.purchase_line_id = pol.id
                      JOIN stock_picking sp ON sp.id = sm.picking_id
                      JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                     WHERE sp.state = 'done'
                       AND spt.code = 'incoming'
                       AND sp.date_done IS NOT NULL
                     GROUP BY pol.order_id
                   ) r ON r.order_id = po.id
             WHERE po.state IN ('purchase', 'done')
               AND po.date_approve IS NOT NULL
               AND po.date_approve >= (NOW() - (%s || ' days')::interval)
               AND r.first_done >= po.date_approve
               AND po.partner_id = ANY(%s)
             GROUP BY po.partner_id
        """, (MEASUREMENT_WINDOW_DAYS, self.ids))
        return {
            partner_id: (float(lead_days or 0.0), int(sample or 0))
            for partner_id, lead_days, sample in self.env.cr.fetchall()
        }

    def _measure_fill_rates(self):
        """{partner_id: proporción entregada} sobre el último año."""
        if not self:
            return {}
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT po.partner_id,
                   SUM(pol.qty_received) / NULLIF(SUM(pol.product_qty), 0) AS fill_rate
              FROM purchase_order_line pol
              JOIN purchase_order po ON po.id = pol.order_id
             WHERE po.state IN ('purchase', 'done')
               AND po.date_approve IS NOT NULL
               AND po.date_approve >= (NOW() - (%s || ' days')::interval)
               AND po.partner_id = ANY(%s)
             GROUP BY po.partner_id
        """, (MEASUREMENT_WINDOW_DAYS, self.ids))
        return {
            partner_id: float(rate or 0.0)
            for partner_id, rate in self.env.cr.fetchall()
        }

    def _lead_time_for_suggestion(self, sellers_by_partner=None):
        """{partner_id: (días de plazo, origen)} con la cascada de respaldo.

        El origen es `measured`, `configured` o `fallback`, y sirve para
        avisarle al usuario cuándo el número es una medición y cuándo una
        suposición.

        Una medición por debajo de un día se descarta: significa que la orden
        de compra se carga cuando la mercadería ya está en el depósito, así que
        la base no tiene registro del plazo real del proveedor.
        """
        measured = self._measure_lead_times()
        sellers_by_partner = sellers_by_partner or {}
        result = {}
        for partner in self:
            days, sample = measured.get(partner.id, (0.0, 0))
            if sample >= MIN_SAMPLE_SIZE and days >= MIN_MEASURABLE_LEAD_TIME_DAYS:
                result[partner.id] = (days, "measured")
                continue
            seller = sellers_by_partner.get(partner.id)
            configured = seller.delay if seller else 0
            if configured:
                result[partner.id] = (float(configured), "configured")
            else:
                result[partner.id] = (FALLBACK_LEAD_TIME_DAYS, "fallback")
        return result

    def action_refresh_purchase_metrics(self):
        """Recalcula y guarda las métricas de estos proveedores."""
        lead_times = self._measure_lead_times()
        fill_rates = self._measure_fill_rates()
        now = fields.Datetime.now()
        for partner in self:
            days, sample = lead_times.get(partner.id, (0.0, 0))
            partner.write({
                "measured_lead_time": days,
                "lead_time_sample_size": sample,
                "fill_rate": fill_rates.get(partner.id, 0.0),
                "metrics_date": now,
            })
        return True

    @api.model
    def _cron_refresh_purchase_metrics(self):
        """Refresca las métricas de todo proveedor con compras en el último año."""
        self.env.cr.execute("""
            SELECT DISTINCT po.partner_id
              FROM purchase_order po
             WHERE po.state IN ('purchase', 'done')
               AND po.date_approve >= (NOW() - (%s || ' days')::interval)
        """, (MEASUREMENT_WINDOW_DAYS,))
        partner_ids = [row[0] for row in self.env.cr.fetchall()]
        partners = self.browse(partner_ids).exists()
        partners.action_refresh_purchase_metrics()
        _logger.info("Métricas de compra actualizadas para %s proveedores",
                     len(partners))
        return True
