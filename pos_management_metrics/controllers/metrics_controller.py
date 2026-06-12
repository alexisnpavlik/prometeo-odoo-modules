# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
import datetime
import csv
import io
import logging

_logger = logging.getLogger(__name__)

class PosMetricsController(http.Controller):

    def _check_access(self):
        if not request.env.user.has_group('pos_management_metrics.group_pos_metrics_user'):
            raise AccessError("No tienes permisos para acceder a las métricas del punto de venta.")

    def _get_timezone(self):
        return request.env.user.tz or 'America/Argentina/Buenos_Aires'

    def _get_lang(self):
        return request.env.context.get('lang') or 'es_AR'

    def _build_where_clause(self, start_date=None, end_date=None, pos='all', cashier='all', company='all', category='all', product='all', search=None):
        # Filtro multi-compañía nativo de Odoo
        allowed_companies = tuple(request.env.companies.ids)
        where_clause = "po.state IN ('done', 'invoiced') AND po.company_id IN %s"
        params = [allowed_companies]
        
        tz = self._get_timezone()
        lang = self._get_lang()

        if start_date:
            where_clause += " AND po.date_order >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            where_clause += " AND po.date_order <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{end_date} 23:59:59", tz])

        if pos and pos != 'all':
            where_clause += " AND pc.name = %s"
            params.append(pos)
        if cashier and cashier != 'all':
            where_clause += " AND COALESCE(emp.name, ru.login) = %s"
            params.append(cashier)
        if company and company != 'all':
            where_clause += " AND rc.name = %s"
            params.append(company)

        # Filtros de línea (Categoría o Producto) mediante EXISTS para optimizar y evitar duplicados a nivel orden
        if (category and category != 'all') or (product and product != 'all'):
            where_clause += """ AND EXISTS (
                SELECT 1 FROM pos_order_line pol2
                JOIN product_product pp2 ON pp2.id = pol2.product_id
                JOIN product_template pt2 ON pt2.id = pp2.product_tmpl_id
                LEFT JOIN product_category ic2 ON ic2.id = pt2.categ_id
                WHERE pol2.order_id = po.id AND pp2.active = TRUE AND pt2.active = TRUE
            """
            if category and category != 'all':
                where_clause += " AND ic2.name = %s"
                params.append(category)
            if product and product != 'all':
                where_clause += " AND COALESCE(pt2.name->>%s, pt2.name->>'en_US') = %s"
                params.extend([lang, product])
            where_clause += ")"

        # Búsqueda difusa
        if search:
            search_pattern = f"%{search.lower()}%"
            where_clause += """ AND (
                LOWER(po.name) LIKE %s OR
                EXISTS (
                    SELECT 1 FROM pos_order_line pol3
                    JOIN product_product pp3 ON pp3.id = pol3.product_id
                    JOIN product_template pt3 ON pt3.id = pp3.product_tmpl_id
                    WHERE pol3.order_id = po.id AND pp3.active = TRUE AND pt3.active = TRUE AND (
                        LOWER(COALESCE(pt3.name->>%s, pt3.name->>'en_US')) LIKE %s
                    )
                ) OR
                EXISTS (
                    SELECT 1 FROM res_partner rp3 WHERE rp3.id = po.partner_id AND LOWER(rp3.name) LIKE %s
                ) OR
                LOWER(COALESCE(emp.name, ru.login)) LIKE %s
            )"""
            params.extend([search_pattern, lang, search_pattern, search_pattern, search_pattern])

        return where_clause, params

    def _build_line_filters(self, category='all', product='all', lang='es_AR'):
        clauses = []
        params = []
        if category and category != 'all':
            clauses.append("ic.name = %s")
            params.append(category)
        if product and product != 'all':
            clauses.append("COALESCE(pt.name->>%s, pt.name->>'en_US') = %s")
            params.extend([lang, product])
        return clauses, params

    @http.route('/pos_management_metrics/filters', type='json', auth='user')
    def get_filters(self, **kwargs):
        self._check_access()
        cr = request.env.cr
        allowed_companies = tuple(request.env.companies.ids)
        lang = self._get_lang()

        # 1. Cajas
        cr.execute("""
            SELECT DISTINCT pc.name 
            FROM pos_order po 
            JOIN pos_config pc ON pc.id = po.config_id 
            WHERE po.state IN ('done', 'invoiced') 
              AND po.company_id IN %s
            ORDER BY pc.name
        """, (allowed_companies,))
        pos_configs = [r[0] for r in cr.fetchall() if r[0]]

        # 2. Cajeros
        cr.execute("""
            SELECT DISTINCT COALESCE(emp.name, ru.login) 
            FROM pos_order po 
            JOIN res_users ru ON ru.id = po.user_id 
            LEFT JOIN hr_employee emp ON emp.user_id = ru.id 
            WHERE po.state IN ('done', 'invoiced') 
              AND po.company_id IN %s
            ORDER BY 1
        """, (allowed_companies,))
        cashiers = [r[0] for r in cr.fetchall() if r[0]]

        # 3. Empresas
        cr.execute("""
            SELECT DISTINCT rc.name 
            FROM pos_order po 
            JOIN res_company rc ON rc.id = po.company_id 
            WHERE po.state IN ('done', 'invoiced') 
              AND po.company_id IN %s
            ORDER BY rc.name
        """, (allowed_companies,))
        companies = [r[0] for r in cr.fetchall() if r[0]]

        # 4. Categorías
        cr.execute("""
            SELECT DISTINCT ic.name 
            FROM product_category ic 
            WHERE LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
            ORDER BY ic.name
        """)
        categories = [r[0] for r in cr.fetchall() if r[0]]

        # 5. Productos (traducido dinámicamente)
        cr.execute("""
            SELECT DISTINCT COALESCE(pt.name->>%s, pt.name->>'en_US') 
            FROM product_template pt
            WHERE pt.active = TRUE
            ORDER BY 1
        """, (lang,))
        products = [r[0] for r in cr.fetchall() if r[0]]

        # 6. Mapa categoría -> productos
        cr.execute("""
            SELECT DISTINCT ic.name, COALESCE(pt.name->>%s, pt.name->>'en_US') 
            FROM product_product pp 
            JOIN product_template pt ON pt.id = pp.product_tmpl_id 
            JOIN product_category ic ON ic.id = pt.categ_id
            WHERE LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
              AND pp.active = TRUE AND pt.active = TRUE
            ORDER BY ic.name, 2
        """, (lang,))
        products_by_category = {}
        for cat, prod in cr.fetchall():
            if cat and prod:
                if cat not in products_by_category:
                    products_by_category[cat] = []
                products_by_category[cat].append(prod)

        # 7. Rango de fechas min/max
        tz = self._get_timezone()
        cr.execute(f"""
            SELECT 
                MIN(date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date, 
                MAX(date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date 
            FROM pos_order 
            WHERE state IN ('done', 'invoiced')
              AND company_id IN %s
        """, (tz, tz, allowed_companies))
        row = cr.fetchone()
        min_date = row[0].strftime('%Y-%m-%d') if row and row[0] else None
        max_date = row[1].strftime('%Y-%m-%d') if row and row[1] else None

        return {
            "pos_configs": pos_configs,
            "cashiers": cashiers,
            "companies": companies,
            "categories": categories,
            "products": products,
            "products_by_category": products_by_category,
            "min_date": min_date,
            "max_date": max_date
        }

    def _get_period_metrics(self, start_date=None, end_date=None, pos='all', cashier='all', company='all', category='all', product='all'):
        cr = request.env.cr
        where_clause, params = self._build_where_clause(start_date, end_date, pos, cashier, company, category, product)
        
        params_list = list(params)
        
        query = f"""
            SELECT
                SUM(pol.price_subtotal_incl) AS total_revenue,
                SUM(pol.price_subtotal) AS total_revenue_net,
                SUM(pol.qty) AS total_qty,
                SUM(pol.qty * COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0)) AS total_cost,
                COUNT(DISTINCT pol.order_id) AS total_orders
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN hr_employee emp ON emp.user_id = ru.id
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
              AND COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0) > 0
        """
        
        lang = self._get_lang()
        line_clauses, line_params = self._build_line_filters(category, product, lang)
        for clause, val in zip(line_clauses, line_params):
            query += f" AND {clause}"
            params_list.append(val)
            
        cr.execute(query, params_list)
        res = cr.dictfetchone() or {}
        
        return {
            "total_revenue": float(res.get("total_revenue") or 0.0),
            "total_revenue_net": float(res.get("total_revenue_net") or 0.0),
            "total_qty": float(res.get("total_qty") or 0.0),
            "total_cost": float(res.get("total_cost") or 0.0),
            "total_orders": int(res.get("total_orders") or 0)
        }

    @http.route('/pos_management_metrics/metrics', type='json', auth='user')
    def get_metrics(self, start_date=None, end_date=None, pos='all', cashier='all', company='all', category='all', product='all', **kwargs):
        self._check_access()
        cr = request.env.cr
        tz = self._get_timezone()
        lang = self._get_lang()
        allowed_companies = tuple(request.env.companies.ids)

        # Construir cláusula de filtrado
        where_clause, params = self._build_where_clause(start_date, end_date, pos, cashier, company, category, product)

        # Obtener IDs de órdenes que coinciden con los filtros y la compañía permitida
        query_orders = f"""
            SELECT DISTINCT po.id
            FROM pos_order po
            JOIN pos_config pc ON pc.id = po.config_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN hr_employee emp ON emp.user_id = ru.id
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause}
        """
        cr.execute(query_orders, params)
        order_ids = [r[0] for r in cr.fetchall()]

        empty_response = {
            "kpis": {
                "total_revenue": 0,
                "total_revenue_net": 0,
                "total_tax": 0,
                "total_orders": 0,
                "ticket_average": 0,
                "cash_difference": 0
            },
            "charts": {
                "sales_trend": {"labels": [], "values": [], "timeframe": "Diario"},
                "sales_by_pos": {"labels": [], "values": []},
                "payment_methods": {"labels": [], "values": []},
                "top_products": {"labels": [], "values": []},
                "top_categories": {"labels": [], "values": []},
                "sales_by_weekday": {"labels": [], "values": []},
                "sales_by_hour": {"labels": [], "values": []}
            },
            "profitability": {
                "product_margins": [],
                "category_margins": [],
                "mom_growth_revenue": 0.0,
                "yoy_growth_revenue": 0.0,
                "unidades_por_ticket": 0.0,
                "total_cost": 0.0,
                "gross_profit": 0.0,
                "margin_percent": 0.0,
                "top_profitable": [],
                "bottom_profitable": []
            }
        }

        if not order_ids:
            return empty_response

        order_ids_tuple = tuple(order_ids)

        # Generar cláusulas de filtrado a nivel de línea
        line_clauses, line_params = self._build_line_filters(category, product, lang)

        # 1. KPIs principales de líneas
        kpi_query = """
            SELECT
                SUM(pol.price_subtotal_incl) AS total_revenue,
                SUM(pol.price_subtotal) AS total_revenue_net,
                COUNT(DISTINCT pol.order_id) AS total_orders
            FROM pos_order_line pol
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
        """
        kpi_params = [order_ids_tuple]
        for clause, val in zip(line_clauses, line_params):
            kpi_query += f" AND {clause}"
            kpi_params.append(val)
            
        cr.execute(kpi_query, kpi_params)
        kpi_row = cr.dictfetchone()
        total_rev = float(kpi_row['total_revenue'] or 0.0)
        total_rev_net = float(kpi_row['total_revenue_net'] or 0.0)
        total_orders = int(kpi_row['total_orders'] or 0)
        total_tax = total_rev - total_rev_net
        ticket_avg = total_rev / total_orders if total_orders > 0 else 0.0

        # 2. Diferencia de arqueo de caja (Sesiones) respetando las compañías permitidas
        sessions_sql = """
            SELECT SUM(
                ps.cash_register_balance_end_real
                - ps.cash_register_balance_start
                - COALESCE(cash.cobrado_efectivo, 0)
                - ps.cash_real_transaction
            ) AS total_diff
            FROM pos_session ps
            JOIN pos_config pc ON pc.id = ps.config_id
            LEFT JOIN (
                SELECT po.session_id, SUM(pay.amount) AS cobrado_efectivo
                FROM pos_payment pay
                JOIN pos_payment_method pm ON pm.id = pay.payment_method_id
                JOIN pos_order po          ON po.id = pay.pos_order_id
                WHERE pm.is_cash_count = TRUE
                GROUP BY po.session_id
            ) cash ON cash.session_id = ps.id
            WHERE ps.state = 'closed'
              AND pc.company_id IN %s
        """
        session_params = [allowed_companies]
        if start_date:
            sessions_sql += " AND ps.stop_at >= %s::timestamp"
            session_params.append(f"{start_date} 00:00:00")
        if end_date:
            sessions_sql += " AND ps.stop_at <= %s::timestamp"
            session_params.append(f"{end_date} 23:59:59")

        cr.execute(sessions_sql, session_params)
        diff_row = cr.fetchone()
        cash_diff = float(diff_row[0]) if diff_row and diff_row[0] is not None else 0.0

        kpis = {
            "total_revenue": round(total_rev, 2),
            "total_revenue_net": round(total_rev_net, 2),
            "total_tax": round(total_tax, 2),
            "total_orders": total_orders,
            "ticket_average": round(ticket_avg, 2),
            "cash_difference": round(cash_diff, 2)
        }

        # --- Gráficos ---

        # 3. Tendencia de Ventas (por hora o día) agrupada por Empresa
        is_small_range = False
        if start_date and end_date:
            d1 = datetime.datetime.strptime(start_date, '%Y-%m-%d')
            d2 = datetime.datetime.strptime(end_date, '%Y-%m-%d')
            if (d2 - d1).days <= 1:
                is_small_range = True

        if is_small_range:
            trend_query = """
                SELECT
                    EXTRACT(hour FROM (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s))::integer AS hora,
                    rc.name AS empresa,
                    SUM(pol.price_subtotal_incl) AS subtotal
                FROM pos_order_line pol
                JOIN pos_order po ON po.id = pol.order_id
                JOIN res_company rc ON rc.id = po.company_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN product_category ic ON ic.id = pt.categ_id
                WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
            """
            trend_params = [tz, order_ids_tuple]
            for clause, val in zip(line_clauses, line_params):
                trend_query += f" AND {clause}"
                trend_params.append(val)
                
            trend_query += """
                GROUP BY hora, rc.name
                ORDER BY hora, rc.name
            """
            cr.execute(trend_query, trend_params)
            trend_rows = cr.fetchall()
            
            unique_times = sorted(list(set(row[0] for row in trend_rows)))
            trend_labels = [f"{h}:00" for h in unique_times]
            timeframe = "Horario"
        else:
            trend_query = """
                SELECT
                    (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS fecha,
                    rc.name AS empresa,
                    SUM(pol.price_subtotal_incl) AS subtotal
                FROM pos_order_line pol
                JOIN pos_order po ON po.id = pol.order_id
                JOIN res_company rc ON rc.id = po.company_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN product_category ic ON ic.id = pt.categ_id
                WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
            """
            trend_params = [tz, order_ids_tuple]
            for clause, val in zip(line_clauses, line_params):
                trend_query += f" AND {clause}"
                trend_params.append(val)
                
            trend_query += """
                GROUP BY fecha, rc.name
                ORDER BY fecha, rc.name
            """
            cr.execute(trend_query, trend_params)
            trend_rows = cr.fetchall()
            
            unique_times = sorted(list(set(row[0] for row in trend_rows if row[0])))
            trend_labels = [d.strftime('%d/%m/%Y') for d in unique_times]
            timeframe = "Diario"

        unique_companies = sorted(list(set(row[1] for row in trend_rows if row[1])))
        
        subtotal_map = {}
        for time_key, company_name, subtotal in trend_rows:
            subtotal_map[(time_key, company_name)] = round(float(subtotal or 0.0), 2)
            
        companies_data = {}
        for company_name in unique_companies:
            companies_data[company_name] = [
                subtotal_map.get((time_key, company_name), 0.0)
                for time_key in unique_times
            ]

        sales_trend = {
            "labels": trend_labels,
            "companies": companies_data,
            "timeframe": timeframe
        }

        # 4. Ventas por Caja
        pos_query = """
            SELECT
                pc.name AS punto_venta,
                SUM(pol.price_subtotal_incl) AS subtotal
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
        """
        pos_params = [order_ids_tuple]
        for clause, val in zip(line_clauses, line_params):
            pos_query += f" AND {clause}"
            pos_params.append(val)
            
        pos_query += """
            GROUP BY pc.name
            ORDER BY subtotal DESC
        """
        cr.execute(pos_query, pos_params)
        pos_rows = cr.fetchall()
        sales_by_pos = {
            "labels": [r[0] for r in pos_rows],
            "values": [round(float(r[1]), 2) for r in pos_rows]
        }

        # 5. Métodos de Pago
        cr.execute("""
            SELECT
                COALESCE(pm.name->>%s, pm.name->>'en_US', 'Desconocido') AS metodo_pago,
                SUM(pay.amount) AS subtotal
            FROM pos_payment pay
            JOIN pos_payment_method pm ON pm.id = pay.payment_method_id
            WHERE pay.pos_order_id IN %s
            GROUP BY pm.name, pm.id
            ORDER BY subtotal DESC
        """, (lang, order_ids_tuple))
        pay_rows = cr.fetchall()
        payment_methods = {
            "labels": [r[0] for r in pay_rows],
            "values": [round(float(r[1]), 2) for r in pay_rows]
        }

        # 6. Top 10 Productos
        prod_query = """
            SELECT
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                SUM(pol.price_subtotal_incl) AS subtotal
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
        """
        prod_params = [lang, order_ids_tuple]
        for clause, val in zip(line_clauses, line_params):
            prod_query += f" AND {clause}"
            prod_params.append(val)
            
        prod_query += """
            GROUP BY producto
            ORDER BY subtotal DESC
            LIMIT 10
        """
        cr.execute(prod_query, prod_params)
        prod_rows = cr.fetchall()
        top_products = {
            "labels": [r[0] for r in prod_rows],
            "values": [round(float(r[1]), 2) for r in prod_rows]
        }

        # 7. Top 10 Categorías
        cat_query = """
            SELECT
                ic.name AS categoria,
                SUM(pol.price_subtotal_incl) AS subtotal
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN product_category ic ON ic.id = pt.categ_id
            WHERE pol.order_id IN %s
              AND LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
              AND pp.active = TRUE AND pt.active = TRUE
        """
        cat_params = [order_ids_tuple]
        for clause, val in zip(line_clauses, line_params):
            cat_query += f" AND {clause}"
            cat_params.append(val)
            
        cat_query += """
            GROUP BY ic.name
            ORDER BY subtotal DESC
            LIMIT 10
        """
        cr.execute(cat_query, cat_params)
        cat_rows = cr.fetchall()
        top_categories = {
            "labels": [r[0] for r in cat_rows],
            "values": [round(float(r[1]), 2) for r in cat_rows]
        }

        # 8. Ventas por Día de la Semana
        order_days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        dow_query = """
            SELECT
                EXTRACT(dow FROM (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s))::integer AS dow,
                SUM(pol.price_subtotal_incl) AS subtotal
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
        """
        dow_params = [tz, order_ids_tuple]
        for clause, val in zip(line_clauses, line_params):
            dow_query += f" AND {clause}"
            dow_params.append(val)
            
        dow_query += " GROUP BY dow"
        cr.execute(dow_query, dow_params)
        dow_data = {r[0]: float(r[1]) for r in cr.fetchall()}
        sales_by_weekday = {
            "labels": order_days,
            "values": [round(dow_data.get(k, 0.0), 2) for k in [1, 2, 3, 4, 5, 6, 0]]
        }

        # 9. Distribución Horaria
        hour_query = """
            SELECT
                EXTRACT(hour FROM (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s))::integer AS hora,
                SUM(pol.price_subtotal_incl) AS subtotal
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
        """
        hour_params = [tz, order_ids_tuple]
        for clause, val in zip(line_clauses, line_params):
            hour_query += f" AND {clause}"
            hour_params.append(val)
            
        hour_query += """
            GROUP BY hora
            ORDER BY hora
        """
        cr.execute(hour_query, hour_params)
        hour_data = {r[0]: float(r[1]) for r in cr.fetchall()}
        sales_by_hour = {
            "labels": [f"{h}:00" for h in range(24)],
            "values": [round(hour_data.get(h, 0.0), 2) for h in range(24)]
        }

        # --- Rentabilidad (Nueva Pestaña) ---
        mom_growth_revenue = 0.0
        yoy_growth_revenue = 0.0
        units_per_ticket = 0.0
        total_cost = 0.0
        gross_profit = 0.0
        margin_percent = 0.0

        # Obtener métricas del período actual completo para KPI base
        current_perf = self._get_period_metrics(start_date, end_date, pos, cashier, company, category, product)
        total_cost = round(current_perf["total_cost"], 2)
        gross_profit = round(current_perf["total_revenue"] - current_perf["total_cost"], 2)
        if current_perf["total_revenue"] > 0:
            margin_percent = round((gross_profit / current_perf["total_revenue"]) * 100.0, 2)
        if current_perf["total_orders"] > 0:
            units_per_ticket = round(current_perf["total_qty"] / current_perf["total_orders"], 2)

        # Crecimiento MoM / YoY: con rango → ese rango; sin rango → último mes calendario como base
        try:
            if start_date and end_date:
                start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
                end_dt = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
                base_perf = current_perf
            else:
                today = datetime.date.today()
                end_dt = today.replace(day=1) - datetime.timedelta(days=1)
                start_dt = end_dt.replace(day=1)
                base_perf = self._get_period_metrics(
                    start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'),
                    pos, cashier, company, category, product
                )

            delta = (end_dt - start_dt).days + 1
            mom_start = (start_dt - datetime.timedelta(days=delta)).strftime('%Y-%m-%d')
            mom_end = (start_dt - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
            try:
                yoy_start = start_dt.replace(year=start_dt.year - 1).strftime('%Y-%m-%d')
            except ValueError:
                yoy_start = (start_dt - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
            try:
                yoy_end = end_dt.replace(year=end_dt.year - 1).strftime('%Y-%m-%d')
            except ValueError:
                yoy_end = (end_dt - datetime.timedelta(days=365)).strftime('%Y-%m-%d')

            mom_perf = self._get_period_metrics(mom_start, mom_end, pos, cashier, company, category, product)
            yoy_perf = self._get_period_metrics(yoy_start, yoy_end, pos, cashier, company, category, product)

            if mom_perf["total_revenue"] > 0:
                mom_growth_revenue = round(((base_perf["total_revenue"] - mom_perf["total_revenue"]) / mom_perf["total_revenue"]) * 100.0, 2)
            else:
                mom_growth_revenue = 100.0 if base_perf["total_revenue"] > 0 else 0.0

            if yoy_perf["total_revenue"] > 0:
                yoy_growth_revenue = round(((base_perf["total_revenue"] - yoy_perf["total_revenue"]) / yoy_perf["total_revenue"]) * 100.0, 2)
            else:
                yoy_growth_revenue = 100.0 if base_perf["total_revenue"] > 0 else 0.0
        except (ValueError, KeyError, TypeError) as e:
            _logger.error(f"Error calculating MoM/YoY growth: {e}")

        # 10. Margen de ganancia por producto
        prod_margin_query = f"""
            SELECT
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                SUM(pol.price_subtotal_incl) AS net_revenue,
                SUM(pol.qty * COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0)) AS total_cost,
                SUM(pol.price_subtotal_incl) - SUM(pol.qty * COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0)) AS gross_profit
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN hr_employee emp ON emp.user_id = ru.id
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
              AND COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0) > 0
        """
        prod_margin_params = [lang] + list(params)
        for clause, val in zip(line_clauses, line_params):
            prod_margin_query += f" AND {clause}"
            prod_margin_params.append(val)
            
        prod_margin_query += """
            GROUP BY producto
            ORDER BY net_revenue DESC
            LIMIT 100
        """
        cr.execute(prod_margin_query, prod_margin_params)
        product_margins = cr.dictfetchall()
        for p in product_margins:
            p['net_revenue'] = round(float(p['net_revenue'] or 0.0), 2)
            p['total_cost'] = round(float(p['total_cost'] or 0.0), 2)
            p['gross_profit'] = round(float(p['gross_profit'] or 0.0), 2)
            p['margin_percent'] = round((p['gross_profit'] / p['net_revenue'] * 100.0), 2) if p['net_revenue'] > 0 else 0.0
        # Descartar productos con costo no cargado o erróneo (margen >= 95% se considera dato basura)
        product_margins = [p for p in product_margins if p['margin_percent'] < 95.0]

        # 11. Margen de ganancia por categoría
        cat_margin_query = f"""
            SELECT
                ic.name AS categoria,
                SUM(pol.price_subtotal_incl) AS net_revenue,
                SUM(pol.qty * COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0)) AS total_cost,
                SUM(pol.price_subtotal_incl) - SUM(pol.qty * COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0)) AS gross_profit
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN hr_employee emp ON emp.user_id = ru.id
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
              AND LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
        """
        cat_margin_params = list(params)
        for clause, val in zip(line_clauses, line_params):
            cat_margin_query += f" AND {clause}"
            cat_margin_params.append(val)
            
        cat_margin_query += """
            GROUP BY ic.name
            ORDER BY net_revenue DESC
        """
        cr.execute(cat_margin_query, cat_margin_params)
        category_margins = cr.dictfetchall()
        for c in category_margins:
            c['net_revenue'] = round(float(c['net_revenue'] or 0.0), 2)
            c['total_cost'] = round(float(c['total_cost'] or 0.0), 2)
            c['gross_profit'] = round(float(c['gross_profit'] or 0.0), 2)
            c['margin_percent'] = round((c['gross_profit'] / c['net_revenue'] * 100.0), 2) if c['net_revenue'] > 0 else 0.0
        category_margins = [c for c in category_margins if c['margin_percent'] < 95.0]

        # 12. Productos con mayor rentabilidad absoluta y fugas de rentabilidad (solo margen negativo)
        top_profitable = sorted([p for p in product_margins if p['gross_profit'] > 0], key=lambda x: x['gross_profit'], reverse=True)[:5]
        bottom_profitable = sorted(
            [p for p in product_margins if p['net_revenue'] > 0 and p['margin_percent'] < 0],
            key=lambda x: x['margin_percent']
        )[:5]

        return {
            "kpis": kpis,
            "charts": {
                "sales_trend": sales_trend,
                "sales_by_pos": sales_by_pos,
                "payment_methods": payment_methods,
                "top_products": top_products,
                "top_categories": top_categories,
                "sales_by_weekday": sales_by_weekday,
                "sales_by_hour": sales_by_hour
            },
            "profitability": {
                "product_margins": product_margins,
                "category_margins": category_margins,
                "mom_growth_revenue": mom_growth_revenue,
                "yoy_growth_revenue": yoy_growth_revenue,
                "unidades_por_ticket": units_per_ticket,
                "total_cost": total_cost,
                "gross_profit": gross_profit,
                "margin_percent": margin_percent,
                "top_profitable": top_profitable,
                "bottom_profitable": bottom_profitable
            }
        }

    @http.route('/pos_management_metrics/sessions', type='json', auth='user')
    def get_sessions(self, **kwargs):
        self._check_access()
        cr = request.env.cr
        tz = self._get_timezone()
        allowed_companies = tuple(request.env.companies.ids)

        query = f"""
            SELECT
                ps.id                               AS sesion_id,
                ps.name                             AS sesion,
                pc.name                             AS punto_venta,
                (ps.start_at AT TIME ZONE 'UTC' AT TIME ZONE %s) AS apertura,
                (ps.stop_at  AT TIME ZONE 'UTC' AT TIME ZONE %s) AS cierre,
                EXTRACT(epoch FROM (ps.stop_at - ps.start_at))/3600 AS horas_abierta,
                COALESCE(emp_open.name, ru_o.login)  AS abierta_por,
                ps.cash_register_balance_start      AS efectivo_apertura,
                ps.cash_real_transaction            AS efectivo_retiros,
                (ps.cash_register_balance_start
                 + COALESCE(cash.cobrado_efectivo, 0)
                 + ps.cash_real_transaction)        AS efectivo_esperado,
                ps.cash_register_balance_end_real   AS efectivo_contado,
                (ps.cash_register_balance_end_real
                 - ps.cash_register_balance_start
                 - COALESCE(cash.cobrado_efectivo, 0)
                 - ps.cash_real_transaction)        AS diferencia_caja,
                COUNT(DISTINCT po.id)               AS cant_ordenes,
                COALESCE(cash.cobrado_efectivo, 0)  AS total_efectivo_cobrado,
                COALESCE(SUM(po.amount_total), 0)   AS total_vendido,
                ps.state                            AS estado_sesion,
                rc.name                             AS empresa
            FROM pos_session              ps
            JOIN pos_config               pc       ON pc.id = ps.config_id
            LEFT JOIN res_users           ru_o     ON ru_o.id = ps.user_id
            LEFT JOIN hr_employee         emp_open ON emp_open.user_id = ru_o.id
            LEFT JOIN pos_order           po       ON po.session_id = ps.id
                                                     AND po.state IN ('done', 'invoiced')
            LEFT JOIN res_company         rc       ON rc.id = pc.company_id
            LEFT JOIN (
                SELECT
                    po.session_id,
                    SUM(pay.amount) AS cobrado_efectivo
                FROM pos_payment pay
                JOIN pos_payment_method pm ON pm.id = pay.payment_method_id
                JOIN pos_order po          ON po.id = pay.pos_order_id
                WHERE pm.is_cash_count = TRUE
                GROUP BY po.session_id
            ) cash ON cash.session_id = ps.id
            WHERE pc.company_id IN %s
            GROUP BY
                ps.id, ps.name, pc.name,
                ps.start_at, ps.stop_at,
                ru_o.login, emp_open.name,
                ps.cash_register_balance_start,
                ps.cash_register_balance_end_real,
                ps.cash_real_transaction,
                cash.cobrado_efectivo,
                ps.state, rc.name
            ORDER BY ps.start_at DESC;
        """
        cr.execute(query, (tz, tz, allowed_companies))
        sessions = cr.dictfetchall()

        # Limpiar registros para serialización JSON segura (evitar NaT/NaN)
        for s in sessions:
            if s['apertura']:
                s['apertura'] = s['apertura'].strftime('%Y-%m-%d %H:%M:%S')
            if s['cierre']:
                s['cierre'] = s['cierre'].strftime('%Y-%m-%d %H:%M:%S')
            s['efectivo_apertura'] = float(s['efectivo_apertura'] or 0.0)
            s['efectivo_retiros'] = float(s['efectivo_retiros'] or 0.0)
            s['efectivo_esperado'] = float(s['efectivo_esperado'] or 0.0)
            s['efectivo_contado'] = float(s['efectivo_contado'] or 0.0)
            s['diferencia_caja'] = float(s['diferencia_caja'] or 0.0)
            s['total_efectivo_cobrado'] = float(s['total_efectivo_cobrado'] or 0.0)
            s['total_vendido'] = float(s['total_vendido'] or 0.0)
            s['horas_abierta'] = float(s['horas_abierta'] or 0.0) if s['horas_abierta'] else 0.0

        return {"sessions": sessions}

    @http.route('/pos_management_metrics/raw_sales', type='json', auth='user')
    def get_raw_sales(self, start_date=None, end_date=None, pos='all', cashier='all', company='all', category='all', product='all', search=None, page=1, per_page=15, **kwargs):
        self._check_access()
        cr = request.env.cr
        tz = self._get_timezone()
        lang = self._get_lang()

        where_clause, params = self._build_where_clause(start_date, end_date, pos, cashier, company, category, product, search)
        line_clauses, line_params = self._build_line_filters(category, product, lang)

        # 1. Contar total de filas para la paginación
        count_query = f"""
            SELECT COUNT(*)
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN hr_employee emp ON emp.user_id = ru.id
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
        """
        count_params = list(params)
        for clause, val in zip(line_clauses, line_params):
            count_query += f" AND {clause}"
            count_params.append(val)

        cr.execute(count_query, count_params)
        total_rows = cr.fetchone()[0] or 0

        total_pages = max(1, (total_rows + per_page - 1) // per_page)
        offset = (page - 1) * per_page

        # 2. Consultar registros paginados
        sales_query = f"""
            SELECT
                po.id                               AS orden_id,
                po.name                             AS numero_orden,
                (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s) AS fecha,
                pc.name                             AS punto_venta,
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                ic.name                             AS categoria,
                pol.qty                             AS cantidad,
                pol.price_unit                      AS precio_unitario,
                pol.price_subtotal_incl             AS subtotal_con_iva,
                rp.name                             AS cliente,
                COALESCE(emp.name, ru.login)        AS cajero
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_partner rp ON rp.id = po.partner_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN hr_employee emp ON emp.user_id = ru.id
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
        """
        sales_params = [tz, lang] + list(params)
        for clause, val in zip(line_clauses, line_params):
            sales_query += f" AND {clause}"
            sales_params.append(val)

        sales_query += f"""
            ORDER BY po.date_order DESC, pol.id DESC
            LIMIT %s OFFSET %s
        """
        sales_params.extend([per_page, offset])

        cr.execute(sales_query, sales_params)
        sales = cr.dictfetchall()

        for s in sales:
            if s['fecha']:
                s['fecha'] = s['fecha'].strftime('%d/%m/%Y %H:%M')
            s['cantidad'] = float(s['cantidad'] or 0.0)
            s['precio_unitario'] = float(s['precio_unitario'] or 0.0)
            s['subtotal_con_iva'] = float(s['subtotal_con_iva'] or 0.0)

        return {
            "sales": sales,
            "page": page,
            "pages": total_pages,
            "total": total_rows
        }

    @http.route('/pos_management_metrics/export', type='http', auth='user')
    def export_csv(self, start_date=None, end_date=None, pos='all', cashier='all', company='all', category='all', product='all', **kwargs):
        try:
            self._check_access()
            cr = request.env.cr
            tz = self._get_timezone()
            lang = self._get_lang()

            # Sanitizar filtros en caso de peticiones http GET planas
            start_date = start_date if start_date and start_date != 'null' and start_date != '' else None
            end_date = end_date if end_date and end_date != 'null' and end_date != '' else None
            pos = pos if pos else 'all'
            cashier = cashier if cashier else 'all'
            company = company if company else 'all'
            category = category if category else 'all'
            product = product if product else 'all'

            where_clause, params = self._build_where_clause(start_date, end_date, pos, cashier, company, category, product)
            line_clauses, line_params = self._build_line_filters(category, product, lang)

            sales_query = f"""
                SELECT
                    po.name                             AS numero_orden,
                    (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s) AS fecha,
                    pc.name                             AS punto_venta,
                    COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                    ic.name                             AS categoria,
                    pol.qty                             AS cantidad,
                    pol.price_unit                      AS precio_unitario,
                    pol.price_subtotal_incl             AS subtotal_con_iva,
                    rp.name                             AS cliente,
                    COALESCE(emp.name, ru.login)        AS cajero
                FROM pos_order_line pol
                JOIN pos_order po ON po.id = pol.order_id
                JOIN pos_config pc ON pc.id = po.config_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN product_category ic ON ic.id = pt.categ_id
                LEFT JOIN res_partner rp ON rp.id = po.partner_id
                LEFT JOIN res_users ru ON ru.id = po.user_id
                LEFT JOIN hr_employee emp ON emp.user_id = ru.id
                LEFT JOIN res_company rc ON rc.id = po.company_id
                WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
            """
            sales_params = [tz, lang] + list(params)
            for clause, val in zip(line_clauses, line_params):
                sales_query += f" AND {clause}"
                sales_params.append(val)

            sales_query += """
                ORDER BY po.date_order DESC, pol.id DESC
            """
            cr.execute(sales_query, sales_params)
            rows = cr.dictfetchall()

            # Escribir CSV
            output = io.StringIO()
            output.write('\ufeff') # Agregar BOM para soporte Excel nativo con acentos
            writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

            writer.writerow([
                'Nro. Orden', 'Fecha', 'Punto de Venta', 'Producto', 'Categoría', 
                'Cantidad', 'Precio Unitario', 'Subtotal Con IVA', 'Cliente', 'Cajero'
            ])

            for row in rows:
                writer.writerow([
                    row['numero_orden'],
                    row['fecha'].strftime('%d/%m/%Y %H:%M') if row['fecha'] else '',
                    row['punto_venta'],
                    row['producto'],
                    row['categoria'] or '',
                    float(row['cantidad'] or 0.0),
                    float(row['precio_unitario'] or 0.0),
                    float(row['subtotal_con_iva'] or 0.0),
                    row['cliente'] or '',
                    row['cajero']
                ])

            csv_data = output.getvalue()
            output.close()

            filename = f"reporte_ventas_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            return request.make_response(
                csv_data,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition', f'attachment; filename="{filename}"')
                ]
            )
        except Exception as e:
            _logger.exception("Error exportando reporte de ventas POS")
            return request.make_response(str(e), status=500)
