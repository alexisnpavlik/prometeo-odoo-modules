# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
import datetime
import csv
import io
import json
import logging
import pytz
import re
import xlsxwriter

_logger = logging.getLogger(__name__)

class PosMetricsController(http.Controller):

    def _check_access(self):
        if not request.env.user.has_group('pos_management_metrics.group_pos_metrics_user'):
            raise AccessError("No tienes permisos para acceder a las métricas del punto de venta.")

    def _get_timezone(self):
        return request.env.user.tz or 'America/Argentina/Buenos_Aires'

    def _get_lang(self):
        return request.env.context.get('lang') or 'es_AR'

    def _normalize_multi(self, value):
        """Normaliza un filtro que puede llegar como string simple, como lista o como JSON.

        El dashboard envía las multi-selecciones serializadas en JSON (también en los
        export por GET, donde una lista se aplanaría con comas y rompería los nombres
        que ya contienen comas). Devuelve None cuando el filtro equivale a "todas/todos"
        (sin filtrar), o una tupla de valores lista para usar con el operador SQL IN.
        """
        if not value or value == 'all':
            return None
        if isinstance(value, str):
            value = value.strip()
            if value.startswith('['):
                try:
                    value = json.loads(value)
                except ValueError:
                    _logger.warning("Filtro multi-selección con JSON inválido: %s", value)
                    return None
            else:
                value = [value]
        if not isinstance(value, (list, tuple)):
            value = [value]
        values = [v for v in value if v and v != 'all']
        return tuple(values) if values else None

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

        pos_configs = self._normalize_multi(pos)
        if pos_configs:
            where_clause += " AND pc.name IN %s"
            params.append(pos_configs)
        # `emp` es un LATERAL que elige UN empleado por usuario (el de la compañía de la venta):
        # un usuario con empleado en varias sucursales duplicaba cada línea con un JOIN simple.
        if cashier and cashier != 'all':
            where_clause += " AND COALESCE(emp.name, ru.login) = %s"
            params.append(cashier)
        companies = self._normalize_multi(company)
        if companies:
            where_clause += " AND rc.name IN %s"
            params.append(companies)

        # Filtros de línea (Categoría o Producto) mediante EXISTS para optimizar y evitar duplicados a nivel orden
        categories = self._normalize_multi(category)
        products = self._normalize_multi(product)
        if categories or products:
            where_clause += """ AND EXISTS (
                SELECT 1 FROM pos_order_line pol2
                JOIN product_product pp2 ON pp2.id = pol2.product_id
                JOIN product_template pt2 ON pt2.id = pp2.product_tmpl_id
                LEFT JOIN product_category ic2 ON ic2.id = pt2.categ_id
                WHERE pol2.order_id = po.id AND pp2.active = TRUE AND pt2.active = TRUE
            """
            if categories:
                where_clause += " AND ic2.name IN %s"
                params.append(categories)
            if products:
                where_clause += " AND COALESCE(pt2.name->>%s, pt2.name->>'en_US') IN %s"
                params.extend([lang, products])
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

    def _surcharge_products_sql(self):
        """Subconsulta con los productos de recargo de las cajas (pos_global_surcharge_button).

        El módulo de recargo no es dependencia de éste: si la columna no existe en la base,
        devuelve una subconsulta vacía para que las consultas sigan funcionando.
        """
        cr = request.env.cr
        cr.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'pos_config' AND column_name = 'surcharge_product_id'
        """)
        if cr.fetchone():
            return "(SELECT surcharge_product_id FROM pos_config WHERE surcharge_product_id IS NOT NULL)"
        return "(SELECT NULL::integer WHERE FALSE)"

    def _non_merchandise_sql(self):
        """Subconsulta con los productos que no son mercadería: descuento global y recargo.

        Entran en la facturación (son plata cobrada o descontada) pero no en rankings ni márgenes.
        """
        return (
            "(SELECT discount_product_id FROM pos_config WHERE discount_product_id IS NOT NULL"
            f" UNION SELECT * FROM {self._surcharge_products_sql()} s)"
        )

    def _build_line_filters(self, category='all', product='all', lang='es_AR'):
        clauses = []
        params = []
        categories = self._normalize_multi(category)
        if categories:
            clauses.append("ic.name IN %s")
            params.append(categories)
        products = self._normalize_multi(product)
        if products:
            clauses.append("COALESCE(pt.name->>%s, pt.name->>'en_US') IN %s")
            params.extend([lang, products])
        return clauses, params

    @http.route('/pos_management_metrics/filters', type='json', auth='user')
    def get_filters(self, **kwargs):
        self._check_access()
        cr = request.env.cr
        non_merch = self._non_merchandise_sql()
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
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
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
        cr.execute(f"""
            SELECT DISTINCT ic.name, COALESCE(pt.name->>%s, pt.name->>'en_US') 
            FROM product_product pp 
            JOIN product_template pt ON pt.id = pp.product_tmpl_id 
            JOIN product_category ic ON ic.id = pt.categ_id
            WHERE LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
              AND pp.active = TRUE AND pt.active = TRUE AND pp.id NOT IN {non_merch}
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
        
        # La línea de descuento global (pos_discount) entra en la facturación, que debe
        # coincidir con lo cobrado; el costo y las unidades salen sólo de productos reales.
        is_discount = "pp.id IN (SELECT discount_product_id FROM pos_config WHERE discount_product_id IS NOT NULL)"
        is_surcharge = f"pp.id IN {self._surcharge_products_sql()}"
        is_merchandise = f"NOT {is_discount} AND NOT {is_surcharge}"
        unit_cost = "COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0)"
        # price_subtotal_incl ya viene neto del descuento de línea: se reconstruye el monto descontado.
        # Al 100% el subtotal es 0 y no hay de dónde despejarlo; se usa qty * price_unit.
        line_discount = """CASE
                    WHEN pol.discount >= 100 THEN pol.qty * pol.price_unit
                    WHEN pol.discount > 0 THEN pol.price_subtotal_incl * pol.discount / (100 - pol.discount)
                    ELSE 0 END"""

        query = f"""
            SELECT
                SUM(pol.price_subtotal_incl) AS total_revenue,
                SUM(pol.price_subtotal) AS total_revenue_net,
                SUM(pol.qty) FILTER (WHERE {is_merchandise} AND po.amount_total >= 0) AS total_qty,
                SUM(pol.price_subtotal_incl) FILTER (WHERE {is_merchandise}) AS products_revenue,
                SUM(pol.price_subtotal_incl) FILTER (WHERE {is_merchandise} AND {unit_cost} > 0) AS costed_revenue,
                SUM(pol.qty * {unit_cost}) FILTER (WHERE {is_merchandise} AND {unit_cost} > 0) AS total_cost,
                SUM(pol.price_subtotal_incl) FILTER (WHERE {is_discount}) AS global_discount,
                SUM(pol.price_subtotal_incl) FILTER (WHERE {is_surcharge}) AS surcharge_total,
                SUM({line_discount}) FILTER (WHERE {is_merchandise}) AS line_discount,
                COUNT(DISTINCT pol.order_id) FILTER (WHERE po.amount_total >= 0) AS total_orders
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
        """

        lang = self._get_lang()
        line_clauses, line_params = self._build_line_filters(category, product, lang)
        query += "".join(f" AND {c}" for c in line_clauses)
        params_list.extend(line_params)

        cr.execute(query, params_list)
        res = cr.dictfetchone() or {}

        return {
            "total_revenue": float(res.get("total_revenue") or 0.0),
            "total_revenue_net": float(res.get("total_revenue_net") or 0.0),
            "total_qty": float(res.get("total_qty") or 0.0),
            "products_revenue": float(res.get("products_revenue") or 0.0),
            "costed_revenue": float(res.get("costed_revenue") or 0.0),
            "total_cost": float(res.get("total_cost") or 0.0),
            # Negativo: es la suma de las líneas de descuento global
            "global_discount": float(res.get("global_discount") or 0.0),
            "line_discount": float(res.get("line_discount") or 0.0),
            "surcharge_total": float(res.get("surcharge_total") or 0.0),
            "total_orders": int(res.get("total_orders") or 0)
        }

    def _get_group_trend(self, group_by, start_date=None, end_date=None, pos='all', cashier='all', company='all', category='all', product='all'):
        """Facturación de cada sucursal (group_by='company') o categoría (group_by='category') en el
        período contra el período anterior de igual largo.

        La columna clave es la variación relativa al total: (1 + var. del grupo) / (1 + var. del total) - 1.
        Una fecha especial (Día del Niño, primavera) mueve a todos los grupos a la vez; medida contra
        el total no aparece como un cambio de uno solo. El total usa todos los filtros salvo el del
        propio agrupamiento (empresa o categoría), que sólo decide qué filas se muestran.
        """
        cr = request.env.cr
        tz = self._get_timezone()
        lang = self._get_lang()
        non_merch = self._non_merchandise_sql()
        empty = {"rows": [], "chain_growth": None, "prev_start": None, "prev_end": None}

        # Los días futuros del rango todavía no existen: contarlos alargaría el período anterior
        today = datetime.datetime.now(pytz.timezone(tz)).date()
        end_dt = min(datetime.datetime.strptime(end_date, '%Y-%m-%d').date(), today) if end_date else today
        # Sin fecha de inicio ("Todo") no hay período anterior: se comparan 4 semanas completas
        if start_date:
            start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_dt = end_dt - datetime.timedelta(days=27)
        if start_dt > end_dt:
            return empty
        days = (end_dt - start_dt).days + 1
        prev_start = start_dt - datetime.timedelta(days=days)
        prev_end = start_dt - datetime.timedelta(days=1)

        if group_by == 'company':
            group_sql = "rc.name"
            visible = self._normalize_multi(company)
            company, extra = 'all', ""
        else:
            # Igual que "Ventas por Categoría": sin descuento/recargo ni las categorías raíz genéricas
            group_sql = "ic.name"
            visible = self._normalize_multi(category)
            category = 'all'
            extra = f" AND pp.id NOT IN {non_merch} AND ic.name IS NOT NULL AND LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')"

        where_clause, params = self._build_where_clause(
            prev_start.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'),
            pos, cashier, company, category, product
        )
        local_ts = "(po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)"
        query = f"""
            SELECT
                {group_sql} AS grupo,
                {local_ts}::date >= %s AS actual,
                (%s::date - {local_ts}::date) / 7 AS bloque,
                SUM(pol.price_subtotal_incl) AS subtotal,
                SUM(pol.qty) FILTER (WHERE pp.id NOT IN {non_merch}) AS unidades
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE{extra}
        """
        query_params = [tz, start_dt, end_dt, tz] + list(params)
        line_clauses, line_params = self._build_line_filters(category, product, lang)
        query += "".join(f" AND {c}" for c in line_clauses)
        query_params.extend(line_params)
        query += " GROUP BY 1, 2, 3"
        cr.execute(query, query_params)

        current, previous, units_cur, units_prev, group_weeks, chain_weeks = {}, {}, {}, {}, {}, {}
        for grupo, actual, bloque, subtotal, unidades in cr.fetchall():
            subtotal = float(subtotal or 0.0)
            unidades = float(unidades or 0.0)
            period, units = (current, units_cur) if actual else (previous, units_prev)
            period[grupo] = period.get(grupo, 0.0) + subtotal
            units[grupo] = units.get(grupo, 0.0) + unidades
            weeks = group_weeks.setdefault(grupo, {})
            weeks[bloque] = weeks.get(bloque, 0.0) + subtotal
            chain_weeks[bloque] = chain_weeks.get(bloque, 0.0) + subtotal

        chain_current = sum(current.values())
        chain_previous = sum(previous.values())
        chain_ratio = chain_current / chain_previous if chain_previous > 0 else 0.0

        # La participación semanal distingue un escalón (cae una vez y se queda) de una tendencia.
        # Bloques de 7 días contados hacia atrás desde el fin del período (0 = el último): todos
        # tienen los mismos días de semana. El más viejo queda incompleto si el total no es múltiplo
        # de 7 y se descarta: un bloque de un domingo daba 100% a la única sucursal abierta.
        full_blocks = (2 * days) // 7
        weeks = list(range(full_blocks - 1, -1, -1)) if full_blocks >= 3 else []
        rows = []
        for grupo in set(current) | set(previous):
            if visible and grupo not in visible:
                continue
            cur = current.get(grupo, 0.0)
            prev = previous.get(grupo, 0.0)
            u_cur = units_cur.get(grupo, 0.0)
            u_prev = units_prev.get(grupo, 0.0)
            growth = vs_chain = units_growth = price_growth = None
            if prev > 0:
                growth = round((cur / prev - 1) * 100.0, 1)
                if chain_ratio > 0:
                    vs_chain = round((cur / prev / chain_ratio - 1) * 100.0, 1)
            # Precio promedio = facturación / unidades: separa "se vendió más" de "se vendió más caro"
            if u_prev > 0:
                units_growth = round((u_cur / u_prev - 1) * 100.0, 1)
                if u_cur > 0 and prev > 0:
                    price_growth = round(((cur / u_cur) / (prev / u_prev) - 1) * 100.0, 1)
            # Menos del 1% del total en los dos períodos: sus porcentajes son ruido (+700% sobre casi nada)
            small = (chain_current <= 0 or cur / chain_current < 0.01) and (chain_previous <= 0 or prev / chain_previous < 0.01)
            name = grupo or ''
            if group_by == 'company':
                name = re.sub(r'^Sucursal\s+', '', name, flags=re.IGNORECASE)
            rows.append({
                "name": name,
                "revenue": round(cur, 2),
                "prev_revenue": round(prev, 2),
                "growth": growth,
                "vs_chain": vs_chain,
                "units_growth": units_growth,
                "price_growth": price_growth,
                "small": small,
                "share": [
                    round(group_weeks[grupo].get(w, 0.0) / chain_weeks[w] * 100.0, 2) if chain_weeks.get(w, 0.0) > 0 else 0.0
                    for w in weeks
                ],
            })
        # Peor primero; los grupos chicos y los sin período anterior (nuevos) van al final
        rows.sort(key=lambda r: (r["small"], r["vs_chain"] is None, r["vs_chain"] or 0.0, -r["revenue"]))

        return {
            "rows": rows,
            "chain_growth": round((chain_ratio - 1) * 100.0, 1) if chain_previous > 0 else None,
            "prev_start": prev_start.strftime('%Y-%m-%d'),
            "prev_end": prev_end.strftime('%Y-%m-%d'),
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
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
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
                "refund_orders": 0,
                "ticket_average": 0,
                "cash_difference": 0,
                "discount_total": 0,
                "discount_global": 0,
                "discount_line": 0,
                "discount_percent": 0,
                "surcharge_total": 0,
                "surcharge_percent": 0
            },
            "charts": {
                "sales_trend": {"labels": [], "values": [], "timeframe": "Diario"},
                "pos_trend": {"labels": [], "configs": {}, "timeframe": "Diario"},
                "sales_by_pos": {"labels": [], "values": []},
                "payment_methods": {"labels": [], "values": []},
                "company_trend": {"rows": [], "chain_growth": None, "prev_start": None, "prev_end": None},
                "category_trend": {"rows": [], "chain_growth": None, "prev_start": None, "prev_end": None},
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
                "cost_coverage_percent": 0.0,
                "products_sold": 0,
                "products_with_cost": 0,
                "products_with_cost_percent": 0.0,
                "top_profitable": [],
                "bottom_profitable": []
            }
        }

        if not order_ids:
            return empty_response

        order_ids_tuple = tuple(order_ids)

        # Generar cláusulas de filtrado a nivel de línea
        line_clauses, line_params = self._build_line_filters(category, product, lang)
        non_merch = self._non_merchandise_sql()

        # 1. KPIs principales de líneas
        kpi_query = """
            SELECT
                SUM(pol.price_subtotal_incl) AS total_revenue,
                SUM(pol.price_subtotal) AS total_revenue_net,
                SUM(pol.price_subtotal_incl) FILTER (WHERE po.amount_total >= 0) AS sales_revenue,
                COUNT(DISTINCT pol.order_id) FILTER (WHERE po.amount_total >= 0) AS total_orders,
                COUNT(DISTINCT pol.order_id) FILTER (WHERE po.amount_total < 0) AS refund_orders
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
        """
        kpi_params = [order_ids_tuple]
        kpi_query += "".join(f" AND {c}" for c in line_clauses)
        kpi_params.extend(line_params)
            
        cr.execute(kpi_query, kpi_params)
        kpi_row = cr.dictfetchone()
        total_rev = float(kpi_row['total_revenue'] or 0.0)
        total_rev_net = float(kpi_row['total_revenue_net'] or 0.0)
        # Las devoluciones (orden con total negativo) restan facturación pero no son tickets:
        # contarlas como transacciones bajaba el ticket promedio.
        total_orders = int(kpi_row['total_orders'] or 0)
        refund_orders = int(kpi_row['refund_orders'] or 0)
        sales_revenue = float(kpi_row['sales_revenue'] or 0.0)
        total_tax = total_rev - total_rev_net
        ticket_avg = sales_revenue / total_orders if total_orders > 0 else 0.0

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
            LEFT JOIN res_company rc ON rc.id = pc.company_id
            LEFT JOIN res_users ru ON ru.id = ps.user_id
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = pc.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            WHERE ps.state = 'closed'
              AND pc.company_id IN %s
        """
        session_params = [allowed_companies]
        if start_date:
            sessions_sql += " AND ps.stop_at >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            session_params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            sessions_sql += " AND ps.stop_at <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            session_params.extend([f"{end_date} 23:59:59", tz])
        session_pos = self._normalize_multi(pos)
        if session_pos:
            sessions_sql += " AND pc.name IN %s"
            session_params.append(session_pos)
        session_companies = self._normalize_multi(company)
        if session_companies:
            sessions_sql += " AND rc.name IN %s"
            session_params.append(session_companies)
        if cashier and cashier != 'all':
            sessions_sql += " AND COALESCE(emp.name, ru.login) = %s"
            session_params.append(cashier)

        cr.execute(sessions_sql, session_params)
        diff_row = cr.fetchone()
        cash_diff = float(diff_row[0]) if diff_row and diff_row[0] is not None else 0.0

        kpis = {
            "total_revenue": round(total_rev, 2),
            "total_revenue_net": round(total_rev_net, 2),
            "total_tax": round(total_tax, 2),
            "total_orders": total_orders,
            "refund_orders": refund_orders,
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
                    pc.name AS caja,
                    SUM(pol.price_subtotal_incl) AS subtotal
                FROM pos_order_line pol
                JOIN pos_order po ON po.id = pol.order_id
                JOIN pos_config pc ON pc.id = po.config_id
                JOIN res_company rc ON rc.id = po.company_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN product_category ic ON ic.id = pt.categ_id
                WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
            """
            trend_params = [tz, order_ids_tuple]
            trend_query += "".join(f" AND {c}" for c in line_clauses)
            trend_params.extend(line_params)
                
            trend_query += """
                GROUP BY hora, rc.name, pc.name
                ORDER BY hora, rc.name, pc.name
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
                    pc.name AS caja,
                    SUM(pol.price_subtotal_incl) AS subtotal
                FROM pos_order_line pol
                JOIN pos_order po ON po.id = pol.order_id
                JOIN pos_config pc ON pc.id = po.config_id
                JOIN res_company rc ON rc.id = po.company_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN product_category ic ON ic.id = pt.categ_id
                WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE
            """
            trend_params = [tz, order_ids_tuple]
            trend_query += "".join(f" AND {c}" for c in line_clauses)
            trend_params.extend(line_params)
                
            trend_query += """
                GROUP BY fecha, rc.name, pc.name
                ORDER BY fecha, rc.name, pc.name
            """
            cr.execute(trend_query, trend_params)
            trend_rows = cr.fetchall()
            
            unique_times = sorted(list(set(row[0] for row in trend_rows if row[0])))
            trend_labels = [d.strftime('%d/%m/%Y') for d in unique_times]
            timeframe = "Diario"

        unique_companies = sorted(list(set(row[1] for row in trend_rows if row[1])))
        unique_configs = sorted(list(set(row[2] for row in trend_rows if row[2])))

        subtotal_map = {}
        config_map = {}
        for time_key, company_name, config_name, subtotal in trend_rows:
            amount = round(float(subtotal or 0.0), 2)
            subtotal_map[(time_key, company_name)] = round(subtotal_map.get((time_key, company_name), 0.0) + amount, 2)
            config_map[(time_key, config_name)] = round(config_map.get((time_key, config_name), 0.0) + amount, 2)

        companies_data = {}
        for company_name in unique_companies:
            companies_data[company_name] = [
                subtotal_map.get((time_key, company_name), 0.0)
                for time_key in unique_times
            ]

        configs_data = {}
        for config_name in unique_configs:
            configs_data[config_name] = [
                config_map.get((time_key, config_name), 0.0)
                for time_key in unique_times
            ]

        sales_trend = {
            "labels": trend_labels,
            "companies": companies_data,
            "timeframe": timeframe
        }

        # Misma evolución temporal, pero comparando cajas (pos.config)
        pos_trend = {
            "labels": trend_labels,
            "configs": configs_data,
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
        pos_query += "".join(f" AND {c}" for c in line_clauses)
        pos_params.extend(line_params)
            
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
            GROUP BY 1
            ORDER BY subtotal DESC
        """, (lang, order_ids_tuple))
        pay_rows = cr.fetchall()
        payment_methods = {
            "labels": [r[0] for r in pay_rows],
            "values": [round(float(r[1]), 2) for r in pay_rows]
        }

        # 5b. Tendencia por sucursal y por categoría contra el total
        company_trend = self._get_group_trend('company', start_date, end_date, pos, cashier, company, category, product)
        category_trend = self._get_group_trend('category', start_date, end_date, pos, cashier, company, category, product)

        # 6. Top 10 Productos
        prod_query = f"""
            SELECT
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                SUM(pol.price_subtotal_incl) AS subtotal
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE pol.order_id IN %s AND pp.active = TRUE AND pt.active = TRUE AND pp.id NOT IN {non_merch}
        """
        prod_params = [lang, order_ids_tuple]
        prod_query += "".join(f" AND {c}" for c in line_clauses)
        prod_params.extend(line_params)
            
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
        cat_query = f"""
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
              AND pp.active = TRUE AND pt.active = TRUE AND pp.id NOT IN {non_merch}
        """
        cat_params = [order_ids_tuple]
        cat_query += "".join(f" AND {c}" for c in line_clauses)
        cat_params.extend(line_params)
            
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
        dow_query += "".join(f" AND {c}" for c in line_clauses)
        dow_params.extend(line_params)
            
        dow_query += " GROUP BY dow"
        cr.execute(dow_query, dow_params)
        dow_data = {r[0]: float(r[1]) for r in cr.fetchall()}

        # Promedio por día calendario: un mes con 5 viernes y 4 sábados no debe
        # inflar el viernes. Un día sin ventas (local cerrado) cuenta como 0.
        if start_date and end_date:
            first_day = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
            last_day = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            cr.execute("""
                SELECT MIN((date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date),
                       MAX((date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date)
                FROM pos_order WHERE id IN %s
            """, (tz, tz, order_ids_tuple))
            first_day, last_day = cr.fetchone()
            if start_date:
                first_day = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
            if end_date:
                last_day = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
        # Los días futuros del rango todavía no existen: no deben bajar el promedio
        last_day = min(last_day, datetime.datetime.now(pytz.timezone(tz)).date())
        weekday_counts = {k: 0 for k in range(7)}
        day = first_day
        while day <= last_day:
            weekday_counts[day.isoweekday() % 7] += 1  # mismo índice que EXTRACT(dow): domingo = 0
            day += datetime.timedelta(days=1)

        sales_by_weekday = {
            "labels": order_days,
            "values": [
                round(dow_data.get(k, 0.0) / weekday_counts[k], 2) if weekday_counts[k] else 0.0
                for k in [1, 2, 3, 4, 5, 6, 0]
            ]
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
        hour_query += "".join(f" AND {c}" for c in line_clauses)
        hour_params.extend(line_params)
            
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
        # El descuento global no se puede atribuir a un producto: se prorratea sobre la parte
        # de la venta que tiene costo cargado, la única que entra en el margen.
        costed_revenue = current_perf["costed_revenue"]
        discount_share = 0.0
        if current_perf["products_revenue"]:
            discount_share = current_perf["global_discount"] * costed_revenue / current_perf["products_revenue"]
        margin_base = costed_revenue + discount_share
        gross_profit = round(margin_base - current_perf["total_cost"], 2)
        if margin_base > 0:
            margin_percent = round((gross_profit / margin_base) * 100.0, 2)
        # Qué parte de la venta de productos tiene costo cargado: el margen sólo habla de esa parte
        cost_coverage_percent = 0.0
        if current_perf["products_revenue"] > 0:
            cost_coverage_percent = round(costed_revenue / current_perf["products_revenue"] * 100.0, 1)

        discount_total = current_perf["line_discount"] - current_perf["global_discount"]
        gross_sales = current_perf["total_revenue"] + discount_total
        kpis["discount_total"] = round(discount_total, 2)
        kpis["discount_global"] = round(-current_perf["global_discount"], 2)
        kpis["discount_line"] = round(current_perf["line_discount"], 2)
        kpis["discount_percent"] = round(discount_total / gross_sales * 100.0, 2) if gross_sales > 0 else 0.0
        surcharge_total = current_perf["surcharge_total"]
        kpis["surcharge_total"] = round(surcharge_total, 2)
        kpis["surcharge_percent"] = round(surcharge_total / current_perf["total_revenue"] * 100.0, 2) if current_perf["total_revenue"] > 0 else 0.0
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
                SUM(pol.qty) AS total_qty,
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
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE AND pp.id NOT IN {non_merch}
              AND COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0) > 0
        """
        prod_margin_params = [lang] + list(params)
        prod_margin_query += "".join(f" AND {c}" for c in line_clauses)
        prod_margin_params.extend(line_params)
            
        prod_margin_query += """
            GROUP BY producto
            ORDER BY net_revenue DESC
            LIMIT 100
        """
        cr.execute(prod_margin_query, prod_margin_params)
        product_margins = cr.dictfetchall()
        for p in product_margins:
            p['total_qty'] = round(float(p['total_qty'] or 0.0), 2)
            p['net_revenue'] = round(float(p['net_revenue'] or 0.0), 2)
            p['total_cost'] = round(float(p['total_cost'] or 0.0), 2)
            p['gross_profit'] = round(float(p['gross_profit'] or 0.0), 2)
            p['margin_percent'] = round((p['gross_profit'] / p['net_revenue'] * 100.0), 2) if p['net_revenue'] > 0 else 0.0
            p['unit_cost'] = round(p['total_cost'] / p['total_qty'], 2) if p['total_qty'] else 0.0
            p['unit_price'] = round(p['net_revenue'] / p['total_qty'], 2) if p['total_qty'] else 0.0
        # Descartar productos con costo no cargado o erróneo (margen >= 95% se considera dato basura)
        product_margins = [p for p in product_margins if p['margin_percent'] < 95.0]

        # 11. Margen de ganancia por categoría
        cat_margin_query = f"""
            SELECT
                ic.name AS categoria,
                SUM(pol.qty) AS total_qty,
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
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE AND pp.id NOT IN {non_merch}
              AND LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
              AND COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0) > 0
        """
        cat_margin_params = list(params)
        cat_margin_query += "".join(f" AND {c}" for c in line_clauses)
        cat_margin_params.extend(line_params)
            
        cat_margin_query += """
            GROUP BY ic.name
            ORDER BY net_revenue DESC
        """
        cr.execute(cat_margin_query, cat_margin_params)
        category_margins = cr.dictfetchall()
        for c in category_margins:
            c['total_qty'] = round(float(c['total_qty'] or 0.0), 2)
            c['net_revenue'] = round(float(c['net_revenue'] or 0.0), 2)
            c['total_cost'] = round(float(c['total_cost'] or 0.0), 2)
            c['gross_profit'] = round(float(c['gross_profit'] or 0.0), 2)
            c['margin_percent'] = round((c['gross_profit'] / c['net_revenue'] * 100.0), 2) if c['net_revenue'] > 0 else 0.0
            c['unit_cost'] = round(c['total_cost'] / c['total_qty'], 2) if c['total_qty'] else 0.0
        category_margins = [c for c in category_margins if c['margin_percent'] < 95.0]

        # 11b. Cobertura de costo: cuántos productos vendidos y qué parte de la venta tienen costo
        # cargado, total y por categoría. El margen sólo habla de esa parte; esto dice cuánto vale.
        # El costo es por compañía: un producto cuenta "con costo" si alguna de sus líneas lo tuvo.
        coverage_query = f"""
            SELECT
                COALESCE(ic.name, 'Sin categoría') AS categoria,
                COUNT(DISTINCT pp.id) AS productos,
                COUNT(DISTINCT pp.id) FILTER (WHERE COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0) > 0) AS productos_con_costo,
                SUM(pol.price_subtotal_incl) AS venta,
                SUM(pol.price_subtotal_incl) FILTER (WHERE COALESCE((pp.standard_price->>(po.company_id::text))::numeric, 0.0) > 0) AS venta_con_costo
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE AND pp.id NOT IN {non_merch}
        """
        coverage_params = list(params)
        coverage_query += "".join(f" AND {c}" for c in line_clauses)
        coverage_params.extend(line_params)
        coverage_query += " GROUP BY 1 ORDER BY venta DESC NULLS LAST"
        cr.execute(coverage_query, coverage_params)
        category_coverage = []
        for row in cr.dictfetchall():
            productos = int(row['productos'] or 0)
            con_costo = int(row['productos_con_costo'] or 0)
            venta = float(row['venta'] or 0.0)
            venta_con_costo = float(row['venta_con_costo'] or 0.0)
            category_coverage.append({
                "categoria": row['categoria'],
                "productos": productos,
                "productos_con_costo": con_costo,
                "productos_percent": round(con_costo / productos * 100.0, 1) if productos else 0.0,
                "venta": round(venta, 2),
                "venta_percent": round(venta_con_costo / venta * 100.0, 1) if venta > 0 else 0.0,
            })
        total_products = sum(c['productos'] for c in category_coverage)
        total_products_with_cost = sum(c['productos_con_costo'] for c in category_coverage)
        products_with_cost_percent = round(total_products_with_cost / total_products * 100.0, 1) if total_products else 0.0

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
                "pos_trend": pos_trend,
                "sales_by_pos": sales_by_pos,
                "payment_methods": payment_methods,
                "company_trend": company_trend,
                "category_trend": category_trend,
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
                "cost_coverage_percent": cost_coverage_percent,
                "products_sold": total_products,
                "products_with_cost": total_products_with_cost,
                "products_with_cost_percent": products_with_cost_percent,
                "top_profitable": top_profitable,
                "bottom_profitable": bottom_profitable
            }
        }

    @http.route('/pos_management_metrics/sessions', type='json', auth='user')
    def get_sessions(self, start_date=None, end_date=None, pos='all', cashier='all', company='all', **kwargs):
        self._check_access()
        cr = request.env.cr
        tz = self._get_timezone()
        allowed_companies = tuple(request.env.companies.ids)

        session_filters = ""
        extra_params = []
        if start_date:
            session_filters += " AND ps.start_at >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            extra_params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            session_filters += " AND ps.start_at <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            extra_params.extend([f"{end_date} 23:59:59", tz])
        pos_configs = self._normalize_multi(pos)
        if pos_configs:
            session_filters += " AND pc.name IN %s"
            extra_params.append(pos_configs)
        companies = self._normalize_multi(company)
        if companies:
            session_filters += " AND rc.name IN %s"
            extra_params.append(companies)
        if cashier and cashier != 'all':
            session_filters += " AND COALESCE(emp_open.name, ru_o.login) = %s"
            extra_params.append(cashier)

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
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru_o.id ORDER BY (e.company_id = pc.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp_open ON TRUE
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
            WHERE pc.company_id IN %s{session_filters}
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
        cr.execute(query, [tz, tz, allowed_companies] + extra_params)
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

    @http.route('/pos_management_metrics/top_articles', type='json', auth='user')
    def get_top_articles(self, start_date=None, end_date=None, pos='all', cashier='all', company='all', category='all', product='all', limit=50, **kwargs):
        """Top de artículos por facturación y por unidades vendidas, respetando los filtros del dashboard."""
        self._check_access()
        cr = request.env.cr
        lang = self._get_lang()

        where_clause, params = self._build_where_clause(start_date, end_date, pos, cashier, company, category, product)
        non_merch = self._non_merchandise_sql()

        query = f"""
            SELECT
                COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                COALESCE(ic.name, 'Sin categoría')        AS categoria,
                SUM(pol.price_subtotal_incl)              AS facturacion,
                SUM(pol.qty)                              AS unidades
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            LEFT JOIN res_users ru ON ru.id = po.user_id
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE AND pp.id NOT IN {non_merch}
        """
        params_list = [lang] + list(params)

        line_clauses, line_params = self._build_line_filters(category, product, lang)
        query += "".join(f" AND {c}" for c in line_clauses)
        params_list.extend(line_params)

        query += " GROUP BY 1, 2"

        cr.execute(query, params_list)
        rows = [
            {
                "producto": r["producto"],
                "categoria": r["categoria"],
                "facturacion": float(r["facturacion"] or 0.0),
                "unidades": float(r["unidades"] or 0.0),
                "precio_unitario": round(float(r["facturacion"] or 0.0) / float(r["unidades"]), 2) if r["unidades"] else 0.0,
            }
            for r in cr.dictfetchall()
        ]

        limit = int(limit or 50)
        by_revenue = sorted(rows, key=lambda r: r["facturacion"], reverse=True)[:limit]
        by_units = sorted(rows, key=lambda r: r["unidades"], reverse=True)[:limit]

        return {"by_revenue": by_revenue, "by_units": by_units}

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
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
        """
        count_params = list(params)
        count_query += "".join(f" AND {c}" for c in line_clauses)
        count_params.extend(line_params)

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
            LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
            LEFT JOIN res_company rc ON rc.id = po.company_id
            WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
        """
        sales_params = [tz, lang] + list(params)
        sales_query += "".join(f" AND {c}" for c in line_clauses)
        sales_params.extend(line_params)

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

    @http.route('/pos_management_metrics/export_top_articles', type='http', auth='user')
    def export_top_articles_xlsx(self, start_date=None, end_date=None, pos='all', cashier='all', company='all', category='all', product='all', limit=50, **kwargs):
        """Exporta a Excel el top de artículos en dos hojas: por total vendido y por unidades."""
        try:
            self._check_access()

            # Sanitizar filtros en caso de peticiones http GET planas
            start_date = start_date if start_date and start_date not in ('null', '') else None
            end_date = end_date if end_date and end_date not in ('null', '') else None
            pos = pos or 'all'
            cashier = cashier or 'all'
            company = company or 'all'
            category = category or 'all'
            product = product or 'all'
            try:
                limit = int(limit or 50)
            except (TypeError, ValueError):
                limit = 50

            data = self.get_top_articles(
                start_date=start_date, end_date=end_date, pos=pos, cashier=cashier,
                company=company, category=category, product=product, limit=limit
            )

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            fmt_title = workbook.add_format({'bold': True, 'font_size': 12})
            fmt_header = workbook.add_format({
                'bold': True, 'bg_color': '#1e293b', 'font_color': '#ffffff',
                'border': 1, 'align': 'center', 'valign': 'vcenter'
            })
            fmt_text = workbook.add_format({'border': 1})
            fmt_money = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
            fmt_qty = workbook.add_format({'border': 1, 'num_format': '#,##0'})

            periodo = f"Período: {start_date or 'inicio'} a {end_date or 'hoy'}"
            sheets = [
                (f"Top {limit} por Total Facturado", data.get("by_revenue") or []),
                (f"Top {limit} por Unidades", data.get("by_units") or []),
            ]

            for sheet_name, rows in sheets:
                sheet = workbook.add_worksheet(sheet_name[:31])
                sheet.set_column(0, 0, 6)
                sheet.set_column(1, 1, 50)
                sheet.set_column(2, 2, 30)
                sheet.set_column(3, 5, 18)

                sheet.write(0, 0, sheet_name, fmt_title)
                sheet.write(1, 0, periodo)
                for col, header in enumerate(['#', 'Artículo', 'Categoría', 'Total Facturado', 'Unidades', 'Precio Unitario']):
                    sheet.write(3, col, header, fmt_header)

                for idx, row in enumerate(rows):
                    line = 4 + idx
                    sheet.write_number(line, 0, idx + 1, fmt_text)
                    sheet.write_string(line, 1, row.get('producto') or '', fmt_text)
                    sheet.write_string(line, 2, row.get('categoria') or '', fmt_text)
                    sheet.write_number(line, 3, float(row.get('facturacion') or 0.0), fmt_money)
                    sheet.write_number(line, 4, round(float(row.get('unidades') or 0.0)), fmt_qty)
                    sheet.write_number(line, 5, float(row.get('precio_unitario') or 0.0), fmt_money)

                sheet.freeze_panes(4, 0)

            workbook.close()
            xlsx_data = output.getvalue()
            output.close()

            filename = f"top_articulos_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            return request.make_response(
                xlsx_data,
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', f'attachment; filename="{filename}"'),
                    ('Content-Length', str(len(xlsx_data))),
                ]
            )
        except Exception as e:
            _logger.exception("Error exportando top de artículos POS")
            return request.make_response(str(e), status=500)

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
                LEFT JOIN LATERAL (SELECT e.name FROM hr_employee e WHERE e.user_id = ru.id ORDER BY (e.company_id = po.company_id) IS TRUE DESC, e.active DESC, e.id LIMIT 1) emp ON TRUE
                LEFT JOIN res_company rc ON rc.id = po.company_id
                WHERE {where_clause} AND pp.active = TRUE AND pt.active = TRUE
            """
            sales_params = [tz, lang] + list(params)
            sales_query += "".join(f" AND {c}" for c in line_clauses)
            sales_params.extend(line_params)

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
