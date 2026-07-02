# -*- coding: utf-8 -*-
import csv
import io
import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

POS_ORDER_STATES = ("paid", "done", "invoiced")


class PosSalesAdvisorController(http.Controller):

    def _check_access(self):
        """Valida que el usuario tenga el grupo de métricas de asesores."""
        if not request.env.user.has_group("pos_sales_advisor.group_pos_advisor_metrics"):
            raise AccessError("No tienes permisos para acceder a las métricas de asesores de venta.")

    def _get_timezone(self):
        """Timezone del usuario para convertir date_order (UTC) a hora local."""
        return request.env.user.tz or "America/Argentina/Buenos_Aires"

    def _build_where_clause(self, start_date=None, end_date=None, advisor="all", pos="all", company="all"):
        """Construye el WHERE parametrizado común a todas las consultas.

        Nota: se incluye el estado 'paid' (a diferencia de pos_management_metrics)
        para ver las ventas del día antes del cierre de sesión.
        """
        allowed_companies = tuple(request.env.companies.ids)
        where = "po.state IN %s AND po.company_id IN %s"
        params = [POS_ORDER_STATES, allowed_companies]
        tz = self._get_timezone()

        if start_date:
            where += " AND po.date_order >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            where += " AND po.date_order <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{end_date} 23:59:59", tz])
        if advisor and advisor != "all":
            where += " AND psa.name = %s"
            params.append(advisor)
        if pos and pos != "all":
            where += " AND pc.name = %s"
            params.append(pos)
        if company and company != "all":
            where += " AND rc.name = %s"
            params.append(company)
        return where, params

    def _base_from(self):
        """FROM común: orden + caja + compañía + asesor (LEFT para medir órdenes sin asesor)."""
        return """
            FROM pos_order po
            JOIN pos_config pc ON pc.id = po.config_id
            JOIN res_company rc ON rc.id = po.company_id
            LEFT JOIN pos_sales_advisor psa ON psa.id = po.sales_advisor_id
        """

    def _get_advisor_rows(self, where, params):
        """Filas agregadas por asesor: bruto, devoluciones, neto, órdenes y ticket promedio."""
        cr = request.env.cr
        cr.execute(f"""
            SELECT psa.name AS asesor,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total >= 0), 0) AS bruto,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total < 0), 0) AS devoluciones,
                   COALESCE(SUM(po.amount_total), 0) AS neto,
                   COUNT(*) FILTER (WHERE po.amount_total >= 0) AS ordenes
            {self._base_from()}
            WHERE {where} AND po.sales_advisor_id IS NOT NULL
            GROUP BY psa.name
            ORDER BY neto DESC
        """, params)
        rows = []
        for asesor, bruto, devoluciones, neto, ordenes in cr.fetchall():
            rows.append({
                "asesor": asesor,
                "bruto": float(bruto),
                "devoluciones": float(devoluciones),
                "neto": float(neto),
                "ordenes": int(ordenes),
                "ticket_promedio": float(bruto) / int(ordenes) if ordenes else 0.0,
            })
        return rows

    def _get_sales_rows(self, where, params, tz, limit=None, offset=0):
        """Ventas individuales atribuidas a un asesor, más recientes primero."""
        cr = request.env.cr
        query = f"""
            SELECT to_char(po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s, 'YYYY-MM-DD HH24:MI') AS fecha,
                   po.pos_reference AS orden,
                   psa.name AS asesor,
                   COALESCE(rp.name, '') AS cliente,
                   po.amount_total AS total
            {self._base_from()}
            LEFT JOIN res_partner rp ON rp.id = po.partner_id
            WHERE {where} AND po.sales_advisor_id IS NOT NULL
            ORDER BY po.date_order DESC
        """
        query_params = [tz] + params
        if limit is not None:
            query += " LIMIT %s OFFSET %s"
            query_params += [limit, offset]
        cr.execute(query, query_params)
        return [
            {
                "fecha": fecha,
                "orden": orden or "",
                "asesor": asesor,
                "cliente": cliente,
                "total": float(total),
            }
            for fecha, orden, asesor, cliente, total in cr.fetchall()
        ]

    @http.route("/pos_sales_advisor/filters", type="json", auth="user")
    def filters_metadata(self):
        """Metadatos para los selects del sidebar del dashboard."""
        self._check_access()
        cr = request.env.cr
        allowed_companies = tuple(request.env.companies.ids)

        cr.execute(
            "SELECT name FROM pos_sales_advisor WHERE company_id IS NULL OR company_id IN %s ORDER BY name",
            [allowed_companies],
        )
        advisors = [r[0] for r in cr.fetchall()]

        cr.execute(
            """
            SELECT pc.name, rc.name
            FROM pos_config pc
            JOIN res_company rc ON rc.id = pc.company_id
            WHERE pc.company_id IN %s
            ORDER BY pc.name
            """,
            [allowed_companies],
        )
        pos_rows = cr.fetchall()
        pos_configs = [r[0] for r in pos_rows]
        pos_configs_by_company = {}
        for pos_name, company_name in pos_rows:
            pos_configs_by_company.setdefault(company_name, []).append(pos_name)

        companies = request.env.companies.mapped("name")

        cr.execute("SELECT MIN(po.date_order)::date, MAX(po.date_order)::date FROM pos_order po WHERE po.company_id IN %s", [allowed_companies])
        min_date, max_date = cr.fetchone()

        return {
            "advisors": advisors,
            "pos_configs": pos_configs,
            "pos_configs_by_company": pos_configs_by_company,
            "companies": sorted(companies),
            "min_date": str(min_date or ""),
            "max_date": str(max_date or ""),
        }

    @http.route("/pos_sales_advisor/metrics", type="json", auth="user")
    def metrics(self, start_date=None, end_date=None, advisor="all", pos="all", company="all"):
        """KPIs, gráficos y tabla de detalle por asesor para el período filtrado."""
        self._check_access()
        cr = request.env.cr
        where, params = self._build_where_clause(start_date, end_date, advisor, pos, company)
        tz = self._get_timezone()

        # --- KPIs de órdenes con asesor ---
        cr.execute(f"""
            SELECT COALESCE(SUM(po.amount_total), 0) AS net_sales,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total >= 0), 0) AS gross_sales,
                   COALESCE(SUM(po.amount_total) FILTER (WHERE po.amount_total < 0), 0) AS refunds,
                   COUNT(*) FILTER (WHERE po.amount_total >= 0) AS orders_count
            {self._base_from()}
            WHERE {where} AND po.sales_advisor_id IS NOT NULL
        """, params)
        net_sales, gross_sales, refunds, orders_count = cr.fetchone()

        # --- KPI de control: órdenes sin asesor en el período (sin filtro de asesor) ---
        where_no_adv, params_no_adv = self._build_where_clause(start_date, end_date, "all", pos, company)
        cr.execute(f"""
            SELECT COUNT(*) FILTER (WHERE po.sales_advisor_id IS NULL) AS without_advisor,
                   COUNT(*) AS total
            {self._base_from()}
            WHERE {where_no_adv}
        """, params_no_adv)
        without_advisor, total_orders = cr.fetchone()

        # --- Tabla / ranking por asesor ---
        table = self._get_advisor_rows(where, params)

        # --- Evolución diaria por asesor (top 6 por neto) ---
        top_names = [r["asesor"] for r in table[:6]]
        trend = {"labels": [], "advisors": {}, "timeframe": "Diario"}
        if top_names:
            cr.execute(f"""
                SELECT to_char(po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s, 'YYYY-MM-DD') AS dia,
                       psa.name AS asesor,
                       SUM(po.amount_total) AS neto
                {self._base_from()}
                WHERE {where} AND psa.name IN %s
                GROUP BY 1, 2
                ORDER BY 1
            """, [tz] + params + [tuple(top_names)])
            raw = cr.fetchall()
            days = sorted({r[0] for r in raw})
            by_advisor = {name: {d: 0.0 for d in days} for name in top_names}
            for dia, asesor, neto in raw:
                by_advisor[asesor][dia] = float(neto)
            trend["labels"] = days
            trend["advisors"] = {name: [by_advisor[name][d] for d in days] for name in top_names}

        # --- Participación (top 8 + Otros) ---
        share_labels = [r["asesor"] for r in table[:8]]
        share_values = [r["neto"] for r in table[:8]]
        rest = sum(r["neto"] for r in table[8:])
        if rest > 0:
            share_labels.append("Otros")
            share_values.append(rest)

        return {
            "kpis": {
                "net_sales": float(net_sales),
                "gross_sales": float(gross_sales),
                "refunds": float(refunds),
                "orders_count": int(orders_count),
                "ticket_average": float(gross_sales) / int(orders_count) if orders_count else 0.0,
                "without_advisor_count": int(without_advisor),
                "without_advisor_pct": round(100.0 * int(without_advisor) / int(total_orders), 1) if total_orders else 0.0,
            },
            "charts": {
                "advisor_ranking": {
                    "labels": [r["asesor"] for r in table[:10]],
                    "values": [r["neto"] for r in table[:10]],
                },
                "sales_trend": trend,
                "advisor_share": {"labels": share_labels, "values": share_values},
            },
            "table": table,
        }

    @http.route("/pos_sales_advisor/export", type="http", auth="user")
    def export_csv(self, start_date=None, end_date=None, advisor="all", pos="all", company="all", **kwargs):
        """Exporta la tabla de detalle por asesor como CSV (insumo para compensaciones)."""
        self._check_access()
        where, params = self._build_where_clause(start_date or None, end_date or None, advisor, pos, company)
        rows = self._get_advisor_rows(where, params)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Asesor", "Ventas Brutas", "Devoluciones", "Ventas Netas", "Órdenes", "Ticket Promedio"])
        for r in rows:
            writer.writerow([
                r["asesor"],
                f"{r['bruto']:.2f}",
                f"{r['devoluciones']:.2f}",
                f"{r['neto']:.2f}",
                r["ordenes"],
                f"{r['ticket_promedio']:.2f}",
            ])

        filename = f"metricas_asesores_{start_date or 'inicio'}_{end_date or 'hoy'}.csv"
        return request.make_response(
            output.getvalue(),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )

    @http.route("/pos_sales_advisor/sales", type="json", auth="user")
    def sales(self, start_date=None, end_date=None, advisor="all", pos="all", company="all", page=1, per_page=50):
        """Listado paginado de ventas individuales por asesor para el período filtrado."""
        self._check_access()
        cr = request.env.cr
        where, params = self._build_where_clause(start_date, end_date, advisor, pos, company)
        tz = self._get_timezone()

        cr.execute(
            f"SELECT COUNT(*) {self._base_from()} WHERE {where} AND po.sales_advisor_id IS NOT NULL",
            params,
        )
        total = cr.fetchone()[0]

        try:
            page = max(1, int(page))
            per_page = max(1, int(per_page))
        except (TypeError, ValueError):
            page, per_page = 1, 50
        pages = max(1, -(-total // per_page))  # ceil
        page = min(page, pages)
        offset = (page - 1) * per_page

        rows = self._get_sales_rows(where, params, tz, limit=per_page, offset=offset)
        return {"sales": rows, "page": page, "pages": pages, "total": total}

    @http.route("/pos_sales_advisor/export_sales", type="http", auth="user")
    def export_sales(self, start_date=None, end_date=None, advisor="all", pos="all", company="all", **kwargs):
        """Exporta las ventas individuales por asesor como CSV, incluyendo la fecha de la venta."""
        self._check_access()
        where, params = self._build_where_clause(start_date or None, end_date or None, advisor, pos, company)
        tz = self._get_timezone()
        rows = self._get_sales_rows(where, params, tz)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Fecha", "Orden", "Asesor", "Cliente", "Total"])
        for r in rows:
            writer.writerow([r["fecha"], r["orden"], r["asesor"], r["cliente"], f"{r['total']:.2f}"])

        filename = f"ventas_asesores_{start_date or 'inicio'}_{end_date or 'hoy'}.csv"
        return request.make_response(
            output.getvalue(),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )
