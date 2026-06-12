# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)

class InventoryMetricsController(http.Controller):

    def _check_access(self):
        if not request.env.user.has_group('inventory_dashboard_metrics.group_inventory_metrics_user'):
            raise AccessError("No tienes permisos para acceder a las métricas de inventario.")

    def _get_lang(self):
        return request.env.context.get('lang') or 'es_AR'

    @http.route('/inventory_dashboard_metrics/filters', type='json', auth='user')
    def get_filters(self, **kwargs):
        self._check_access()
        cr = request.env.cr
        allowed_companies = tuple(request.env.companies.ids)
        lang = self._get_lang()

        if not allowed_companies:
            return {
                "companies": [],
                "categories": [],
                "products": []
            }

        # 1. Empresas permitidas
        cr.execute("""
            SELECT DISTINCT rc.name 
            FROM res_company rc 
            WHERE rc.id IN %s
            ORDER BY rc.name
        """, (allowed_companies,))
        companies = [r[0] for r in cr.fetchall() if r[0]]

        # 2. Categorías comerciales
        cr.execute("""
            SELECT DISTINCT ic.name 
            FROM product_category ic 
            WHERE LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
            ORDER BY ic.name
        """)
        categories = [r[0] for r in cr.fetchall() if r[0]]

        # 3. Productos activos (traducidos dinámicamente)
        cr.execute("""
            SELECT DISTINCT COALESCE(pt.name->>%s, pt.name->>'en_US') 
            FROM product_template pt
            WHERE pt.active = TRUE
            ORDER BY 1
        """, (lang,))
        products = [r[0] for r in cr.fetchall() if r[0]]

        return {
            "companies": companies,
            "categories": categories,
            "products": products
        }

    @http.route('/inventory_dashboard_metrics/inventory', type='json', auth='user')
    def get_inventory(self, company='all', **kwargs):
        self._check_access()
        cr = request.env.cr
        # Obtener y validar el filtro de tiempo (período en días)
        try:
            period = int(kwargs.get('period') or 30)
            if period not in (7, 15, 30, 60, 90):
                period = 30
        except ValueError:
            period = 30

        lang = self._get_lang()

        # Configuración de filtro multi-compañía
        if company and company != 'all':
            cr.execute("SELECT id FROM res_company WHERE name = %s", (company,))
            comp_row = cr.fetchone()
            allowed_companies = (comp_row[0],) if comp_row else tuple(request.env.companies.ids)
        else:
            allowed_companies = tuple(request.env.companies.ids)

        if not allowed_companies:
            return {
                "kpis": {"total_value": 0, "total_units": 0, "stockouts": 0, "low_stock": 0},
                "category_valuation": [],
                "top_movements": {"labels": [], "values": []},
                "top_value_products": [],
                "critical_stock_alerts": []
            }

        selected_comp_str = str(allowed_companies[0])

        # 1. KPIs principales de Inventario
        cr.execute("""
            WITH product_stock AS (
                SELECT 
                    pp.id AS product_id,
                    COALESCE(SUM(sq.quantity), 0.0) AS total_stock,
                    SUM(COALESCE(sq.quantity, 0.0) * COALESCE(
                        (pp.standard_price->>(sq.company_id::text))::numeric, 
                        (pp.standard_price->>'1')::numeric, 
                        0.0
                    )) AS total_value
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN stock_quant sq ON sq.product_id = pp.id 
                    AND sq.company_id IN %s
                    AND sq.location_id IN (
                        SELECT id FROM stock_location WHERE usage = 'internal' AND active = TRUE
                    )
                WHERE pp.active = TRUE AND pt.active = TRUE
                GROUP BY pp.id
            )
            SELECT
                SUM(total_value) AS total_value,
                SUM(CASE WHEN total_stock > 0 THEN total_stock ELSE 0.0 END) AS total_units,
                COUNT(CASE WHEN total_stock <= 0 THEN 1 END) AS stockouts,
                COUNT(CASE WHEN total_stock > 0 AND total_stock <= 10 THEN 1 END) AS low_stock
            FROM product_stock
        """, (allowed_companies,))
        kpi_res = cr.dictfetchone() or {}
        
        total_value = float(kpi_res.get("total_value") or 0.0)
        total_units = float(kpi_res.get("total_units") or 0.0)
        stockouts = int(kpi_res.get("stockouts") or 0)
        low_stock = int(kpi_res.get("low_stock") or 0)

        # 2. Valoración de Stock por Categoría
        cr.execute("""
            WITH product_stock AS (
                SELECT 
                    pp.id AS product_id,
                    pt.categ_id,
                    COALESCE(SUM(sq.quantity), 0.0) AS total_stock,
                    SUM(COALESCE(sq.quantity, 0.0) * COALESCE(
                        (pp.standard_price->>(sq.company_id::text))::numeric, 
                        (pp.standard_price->>'1')::numeric, 
                        0.0
                    )) AS total_value
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN stock_quant sq ON sq.product_id = pp.id 
                    AND sq.company_id IN %s
                    AND sq.location_id IN (
                        SELECT id FROM stock_location WHERE usage = 'internal' AND active = TRUE
                    )
                WHERE pp.active = TRUE AND pt.active = TRUE
                GROUP BY pp.id, pt.categ_id
            )
            SELECT
                ic.name AS categoria,
                SUM(CASE WHEN ps.total_stock > 0 THEN ps.total_stock ELSE 0.0 END) AS total_qty,
                SUM(ps.total_value) AS total_value
            FROM product_stock ps
            JOIN product_category ic ON ic.id = ps.categ_id
            WHERE LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
            GROUP BY ic.name
            HAVING SUM(CASE WHEN ps.total_stock > 0 THEN ps.total_stock ELSE 0.0 END) > 0 OR SUM(ps.total_value) > 0
            ORDER BY total_value DESC
        """, (allowed_companies,))
        cat_valuation = cr.dictfetchall()
        for c in cat_valuation:
            c['total_qty'] = float(c['total_qty'] or 0.0)
            c['total_value'] = round(float(c['total_value'] or 0.0), 2)
            c['value_percent'] = round((c['total_value'] / total_value * 100.0), 2) if total_value > 0 else 0.0

        # 3. Top 10 Movimientos / Rotación (dinámico según período)
        cr.execute("""
            SELECT
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS product,
                SUM(sm.product_uom_qty) AS qty
            FROM stock_move sm
            JOIN product_product pp ON pp.id = sm.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE sm.state = 'done'
              AND sm.date >= NOW() - CAST(%s || ' days' AS INTERVAL)
              AND sm.company_id IN %s
              AND pp.active = TRUE AND pt.active = TRUE
            GROUP BY product
            ORDER BY qty DESC
            LIMIT 10
        """, (lang, str(period), allowed_companies))
        move_rows = cr.fetchall()
        top_movements = {
            "labels": [r[0] for r in move_rows],
            "values": [float(r[1]) for r in move_rows]
        }

        # 4. Top 10 Productos con Mayor Valor de Inventario
        cr.execute("""
            WITH product_stock AS (
                SELECT 
                    pp.id AS product_id,
                    COALESCE(SUM(sq.quantity), 0.0) AS total_stock,
                    SUM(COALESCE(sq.quantity, 0.0) * COALESCE(
                        (pp.standard_price->>(sq.company_id::text))::numeric, 
                        (pp.standard_price->>'1')::numeric, 
                        0.0
                    )) AS total_value,
                    CASE WHEN COALESCE(SUM(sq.quantity), 0.0) > 0 THEN
                        SUM(COALESCE(sq.quantity, 0.0) * COALESCE(
                            (pp.standard_price->>(sq.company_id::text))::numeric, 
                            (pp.standard_price->>'1')::numeric, 
                            0.0
                        )) / SUM(sq.quantity)
                    ELSE 0.0 END AS avg_unit_cost
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN stock_quant sq ON sq.product_id = pp.id 
                    AND sq.company_id IN %s
                    AND sq.location_id IN (
                        SELECT id FROM stock_location WHERE usage = 'internal' AND active = TRUE
                    )
                WHERE pp.active = TRUE AND pt.active = TRUE
                GROUP BY pp.id
            )
            SELECT
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                ic.name AS categoria,
                ps.total_stock AS stock,
                ps.avg_unit_cost AS costo,
                ps.total_value AS total_value
            FROM product_stock ps
            JOIN product_product pp ON pp.id = ps.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE ps.total_stock > 0
            ORDER BY total_value DESC
            LIMIT 10
        """, (allowed_companies, lang))
        top_value_products = cr.dictfetchall()
        for p in top_value_products:
            p['stock'] = float(p['stock'] or 0.0)
            p['costo'] = round(float(p['costo'] or 0.0), 2)
            p['total_value'] = round(float(p['total_value'] or 0.0), 2)

        # 5. Alertas de Stock Crítico (≤ 10 unidades)
        cr.execute("""
            WITH product_stock AS (
                SELECT 
                    pp.id AS product_id,
                    COALESCE(SUM(sq.quantity), 0.0) AS total_stock,
                    SUM(COALESCE(sq.quantity, 0.0) * COALESCE(
                        (pp.standard_price->>(sq.company_id::text))::numeric, 
                        (pp.standard_price->>'1')::numeric, 
                        0.0
                    )) AS total_value,
                    CASE WHEN COALESCE(SUM(sq.quantity), 0.0) > 0 THEN
                        SUM(COALESCE(sq.quantity, 0.0) * COALESCE(
                            (pp.standard_price->>(sq.company_id::text))::numeric, 
                            (pp.standard_price->>'1')::numeric, 
                            0.0
                        )) / SUM(sq.quantity)
                    ELSE
                        COALESCE(
                            (pp.standard_price->>(%s::text))::numeric, 
                            (pp.standard_price->>'1')::numeric, 
                            0.0
                        )
                    END AS avg_unit_cost
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN stock_quant sq ON sq.product_id = pp.id 
                    AND sq.company_id IN %s
                    AND sq.location_id IN (
                        SELECT id FROM stock_location WHERE usage = 'internal' AND active = TRUE
                    )
                WHERE pp.active = TRUE AND pt.active = TRUE
                GROUP BY pp.id
            )
            SELECT
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                ic.name AS categoria,
                ps.total_stock AS stock,
                ps.avg_unit_cost AS costo,
                ps.total_value AS total_value
            FROM product_stock ps
            JOIN product_product pp ON pp.id = ps.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE ps.total_stock <= 10
            ORDER BY ps.total_stock ASC
            LIMIT 100
        """, (selected_comp_str, allowed_companies, lang))
        critical_stock_alerts = cr.dictfetchall()
        for a in critical_stock_alerts:
            a['stock'] = float(a['stock'] or 0.0)
            a['costo'] = round(float(a['costo'] or 0.0), 2)
            a['total_value'] = round(float(a['total_value'] or 0.0), 2)

        # 6. Heatmap de Cobertura de Stock por Sucursal
        cr.execute("""
            SELECT id, name FROM res_company WHERE id IN %s ORDER BY id
        """, (allowed_companies,))
        company_rows = cr.dictfetchall()
        heatmap_companies = [{"id": r["id"], "name": r["name"]} for r in company_rows]

        cr.execute("""
            WITH target_products AS (
                SELECT 
                    pp.id AS product_id,
                    COALESCE(pt.name->>%s, pt.name->>'en_US') AS product_name,
                    SUM(sq.quantity * COALESCE((pp.standard_price->>(sq.company_id::text))::numeric, (pp.standard_price->>'1')::numeric, 0.0)) AS total_val
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                JOIN stock_quant sq ON sq.product_id = pp.id
                JOIN stock_location sl ON sl.id = sq.location_id AND sl.usage = 'internal' AND sl.active = TRUE
                WHERE pp.active = TRUE AND pt.active = TRUE
                  AND sq.company_id IN %s
                GROUP BY pp.id, pt.name
                ORDER BY total_val DESC NULLS LAST
                LIMIT 15
            ),
            stock_data AS (
                SELECT 
                    sq.product_id,
                    sq.company_id,
                    SUM(sq.quantity) AS stock
                FROM stock_quant sq
                JOIN stock_location sl ON sl.id = sq.location_id
                WHERE sl.usage = 'internal' AND sl.active = TRUE
                  AND sq.company_id IN %s
                GROUP BY sq.product_id, sq.company_id
            ),
            sales_data AS (
                SELECT 
                    sm.product_id,
                    sm.company_id,
                    SUM(sm.product_uom_qty) AS sales_30d
                FROM stock_move sm
                JOIN stock_location sld ON sld.id = sm.location_dest_id
                JOIN stock_location sls ON sls.id = sm.location_id
                WHERE sm.state = 'done'
                  AND sld.usage = 'customer'
                  AND sls.usage = 'internal'
                  AND sm.company_id IN %s
                  AND sm.date >= NOW() - CAST(%s || ' days' AS INTERVAL)
                GROUP BY sm.product_id, sm.company_id
            )
            SELECT 
                tp.product_id,
                tp.product_name,
                rc.id AS company_id,
                rc.name AS company_name,
                COALESCE(sd.stock, 0.0) AS stock,
                COALESCE(sa.sales_30d, 0.0) AS sales_30d
            FROM target_products tp
            CROSS JOIN res_company rc
            LEFT JOIN stock_data sd ON sd.product_id = tp.product_id AND sd.company_id = rc.id
            LEFT JOIN sales_data sa ON sa.product_id = tp.product_id AND sa.company_id = rc.id
            WHERE rc.id IN %s
            ORDER BY tp.total_val DESC, tp.product_name ASC, rc.id ASC
        """, (lang, allowed_companies, allowed_companies, allowed_companies, str(period), allowed_companies))
        
        heatmap_rows = cr.dictfetchall()
        
        heatmap_dict = {}
        for r in heatmap_rows:
            p_id = r["product_id"]
            if p_id not in heatmap_dict:
                heatmap_dict[p_id] = {
                    "product_id": p_id,
                    "product_name": r["product_name"],
                    "coverages": {}
                }
            
            stock = float(r["stock"] or 0.0)
            sales = float(r["sales_30d"] or 0.0)
            daily_sales = sales / float(period)
            
            if daily_sales > 0:
                coverage = int(round(stock / daily_sales))
            else:
                coverage = None
            
            heatmap_dict[p_id]["coverages"][str(r["company_id"])] = coverage

        heatmap_data = []
        seen = set()
        for r in heatmap_rows:
            p_id = r["product_id"]
            if p_id not in seen:
                heatmap_data.append(heatmap_dict[p_id])
                seen.add(p_id)

        # 7. Métricas de Dead Stock (stock > 0 pero sin ventas en los últimos N días)
        cr.execute("""
            SELECT 
                pp.id AS product_id,
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS product_name,
                SUM(sq.quantity) AS stock,
                SUM(sq.quantity * COALESCE((pp.standard_price->>(sq.company_id::text))::numeric, (pp.standard_price->>'1')::numeric, 0.0)) AS dead_val
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN stock_quant sq ON sq.product_id = pp.id
            JOIN stock_location sl ON sl.id = sq.location_id AND sl.usage = 'internal' AND sl.active = TRUE
            WHERE pp.active = TRUE AND pt.active = TRUE
              AND sq.company_id IN %s
              AND pp.id NOT IN (
                  SELECT DISTINCT sm.product_id
                  FROM stock_move sm
                  JOIN stock_location sld ON sld.id = sm.location_dest_id
                  JOIN stock_location sls ON sls.id = sm.location_id
                  WHERE sm.state = 'done'
                    AND sld.usage = 'customer'
                    AND sls.usage = 'internal'
                    AND sm.company_id IN %s
                    AND sm.date >= NOW() - CAST(%s || ' days' AS INTERVAL)
              )
            GROUP BY pp.id, pt.name
            HAVING SUM(sq.quantity) > 0
            ORDER BY dead_val DESC, stock DESC
            LIMIT 10
        """, (lang, allowed_companies, allowed_companies, str(period)))
        
        dead_rows = cr.dictfetchall()
        dead_stock = {
            "labels": [r["product_name"] for r in dead_rows],
            "values": [float(r["dead_val"]) for r in dead_rows],
            "stocks": [float(r["stock"]) for r in dead_rows]
        }

        return {
            "kpis": {
                "total_value": round(total_value, 2),
                "total_units": round(total_units, 2),
                "stockouts": stockouts,
                "low_stock": low_stock
            },
            "category_valuation": cat_valuation,
            "top_movements": top_movements,
            "top_value_products": top_value_products,
            "critical_stock_alerts": critical_stock_alerts,
            "heatmap_companies": heatmap_companies,
            "heatmap_data": heatmap_data,
            "dead_stock": dead_stock
        }
