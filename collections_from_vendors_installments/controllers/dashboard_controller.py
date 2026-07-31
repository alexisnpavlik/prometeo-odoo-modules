# -*- coding: utf-8 -*-
import csv
import io
import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)

CARD_STATES = {
    "draft": "Borrador",
    "sold": "Vendida",
    "routed": "Enrutada",
    "active": "En cobranza",
    "done": "Finalizada",
    "recovered": "Retirada",
    "cancel": "Anulada",
}

INSTALLMENT_STATES = {
    "pending": "Pendiente",
    "partial": "Parcial",
    "paid": "Pagada",
    "overdue": "Vencida",
}

# Tramos de antigüedad de deuda que pide HU-32. El último es abierto.
AGING_BUCKETS = [
    ("1 a 30 días", 1, 30),
    ("31 a 60 días", 31, 60),
    ("61 a 90 días", 61, 90),
    ("Más de 90 días", 91, None),
]


class CviDashboardController(http.Controller):

    def _check_access(self, env=None):
        """Solo el administrador de cobranzas ve el tablero (HU-32)."""
        env = env or request.env
        if not env.user.has_group(
            "collections_from_vendors_installments.group_cvi_manager"
        ):
            raise AccessError(
                "No tenés permisos para acceder al tablero de venta en cuotas."
            )

    def _cvi_where(self, env, start_date, end_date, company, alias="c"):
        """WHERE parametrizado sobre cvi_card, scopeado a las empresas del usuario.

        Excluye borradores y anuladas: una venta sin confirmar no es negocio.
        """
        where = (
            f"{alias}.state NOT IN ('draft', 'cancel') "
            f"AND {alias}.company_id IN %s"
        )
        params = [tuple(env.companies.ids)]
        if start_date:
            where += f" AND {alias}.date_sale >= %s"
            params.append(start_date)
        if end_date:
            where += f" AND {alias}.date_sale <= %s"
            params.append(end_date)
        if company and company != "all":
            where += f" AND {alias}.company_id = %s"
            params.append(int(company))
        return where, params

    def _resolve_names(self, env, model, ids):
        """Resuelve {id: display_name} por ORM, evitando SQL sobre columnas jsonb."""
        ids = [i for i in set(ids) if i]
        if not ids:
            return {}
        return {rec.id: rec.display_name for rec in env[model].sudo().browse(ids)}

    def _cvi_kpis(self, env, start_date, end_date, company):
        """Indicadores de cabecera del período."""
        env.flush_all()
        where, params = self._cvi_where(env, start_date, end_date, company)

        env.cr.execute(f"""
            SELECT COUNT(*) AS card_count,
                   COALESCE(SUM(c.amount_total), 0) AS sold,
                   COALESCE(SUM(c.amount_residual), 0) AS residual,
                   COUNT(*) FILTER (WHERE c.state = 'recovered') AS recovered_count,
                   COUNT(*) FILTER (WHERE c.to_recover) AS to_recover_count
            FROM cvi_card c
            WHERE {where}
        """, params)
        cards = env.cr.dictfetchone() or {}

        env.cr.execute(f"""
            SELECT COALESCE(SUM(i.amount_residual) FILTER (
                       WHERE i.state = 'overdue' AND NOT i.is_commission
                   ), 0) AS overdue_amount,
                   COUNT(*) FILTER (
                       WHERE i.state = 'overdue' AND NOT i.is_commission
                   ) AS overdue_installments,
                   COUNT(*) FILTER (WHERE NOT i.is_commission) AS installment_count
            FROM cvi_installment i
            JOIN cvi_card c ON c.id = i.card_id
            WHERE {where}
        """, params)
        installments = env.cr.dictfetchone() or {}

        # Lo cobrado se mide por fecha del cobro, no por fecha de la venta: si no, un
        # cobro de este mes sobre una venta vieja no aparecería en ningún período.
        pay_where = "p.state = 'posted' AND p.company_id IN %s AND NOT p.is_commission"
        pay_params = [tuple(env.companies.ids)]
        if start_date:
            pay_where += " AND p.date >= %s"
            pay_params.append(start_date)
        if end_date:
            pay_where += " AND p.date <= %s"
            pay_params.append(end_date)
        if company and company != "all":
            pay_where += " AND p.company_id = %s"
            pay_params.append(int(company))
        env.cr.execute(f"""
            SELECT COALESCE(SUM(p.amount), 0) AS collected, COUNT(*) AS payment_count
            FROM cvi_payment p WHERE {pay_where}
        """, pay_params)
        payments = env.cr.dictfetchone() or {}

        total_installments = installments.get("installment_count") or 0
        overdue_installments = installments.get("overdue_installments") or 0
        return {
            "sold": float(cards.get("sold") or 0),
            "card_count": int(cards.get("card_count") or 0),
            "residual": float(cards.get("residual") or 0),
            "collected": float(payments.get("collected") or 0),
            "payment_count": int(payments.get("payment_count") or 0),
            "overdue_amount": float(installments.get("overdue_amount") or 0),
            "overdue_installments": int(overdue_installments),
            "overdue_rate": round(
                overdue_installments / total_installments * 100, 1
            ) if total_installments else 0.0,
            "recovered_count": int(cards.get("recovered_count") or 0),
            "to_recover_count": int(cards.get("to_recover_count") or 0),
        }

    def _cvi_charts(self, env, start_date, end_date, company):
        """Las series de los reportes mínimos que enumera HU-32."""
        env.flush_all()
        where, params = self._cvi_where(env, start_date, end_date, company)

        # 1. Ventas por vendedor y por período.
        env.cr.execute(f"""
            SELECT to_char(date_trunc('month', c.date_sale), 'YYYY-MM') AS period,
                   c.vendor_id,
                   COALESCE(SUM(c.amount_total), 0) AS total
            FROM cvi_card c
            WHERE {where}
            GROUP BY period, c.vendor_id
            ORDER BY period
        """, params)
        vendor_rows = env.cr.dictfetchall()
        vendor_names = self._resolve_names(
            env, "res.users", [r["vendor_id"] for r in vendor_rows]
        )
        periods = sorted({r["period"] for r in vendor_rows})
        vendor_series = {}
        for row in vendor_rows:
            name = vendor_names.get(row["vendor_id"], "N/D")
            series = vendor_series.setdefault(name, [0.0] * len(periods))
            series[periods.index(row["period"])] = float(row["total"])

        # 2. Cartera por cobrador: saldo, cobrado del período y mora.
        env.cr.execute(f"""
            SELECT c.collector_id,
                   COALESCE(SUM(c.amount_residual), 0) AS residual,
                   COALESCE(SUM(c.amount_overdue), 0) AS overdue
            FROM cvi_card c
            WHERE {where} AND c.collector_id IS NOT NULL
            GROUP BY c.collector_id
            ORDER BY residual DESC
            LIMIT 15
        """, params)
        portfolio_rows = env.cr.dictfetchall()
        collector_ids = [r["collector_id"] for r in portfolio_rows]
        collector_names = self._resolve_names(env, "res.users", collector_ids)

        collected_by_collector = {}
        if collector_ids:
            pay_where = (
                "p.state = 'posted' AND p.company_id IN %s AND NOT p.is_commission "
                "AND p.user_id IN %s"
            )
            pay_params = [tuple(env.companies.ids), tuple(collector_ids)]
            if start_date:
                pay_where += " AND p.date >= %s"
                pay_params.append(start_date)
            if end_date:
                pay_where += " AND p.date <= %s"
                pay_params.append(end_date)
            env.cr.execute(f"""
                SELECT p.user_id, COALESCE(SUM(p.amount), 0) AS collected
                FROM cvi_payment p WHERE {pay_where} GROUP BY p.user_id
            """, pay_params)
            collected_by_collector = {
                r["user_id"]: float(r["collected"]) for r in env.cr.dictfetchall()
            }

        # 3. Antigüedad de deuda (aging).
        aging_labels, aging_values = [], []
        for label, low, high in AGING_BUCKETS:
            bucket_where = where + (
                " AND i.state = 'overdue' AND NOT i.is_commission"
                " AND (CURRENT_DATE - i.date_due) >= %s"
            )
            bucket_params = list(params) + [low]
            if high is not None:
                bucket_where += " AND (CURRENT_DATE - i.date_due) <= %s"
                bucket_params.append(high)
            env.cr.execute(f"""
                SELECT COALESCE(SUM(i.amount_residual), 0) AS amount
                FROM cvi_installment i
                JOIN cvi_card c ON c.id = i.card_id
                WHERE {bucket_where}
            """, bucket_params)
            aging_labels.append(label)
            aging_values.append(float((env.cr.dictfetchone() or {}).get("amount") or 0))

        # 4. Rendiciones con diferencias.
        settle_where = "s.company_id IN %s AND s.has_difference"
        settle_params = [tuple(env.companies.ids)]
        if start_date:
            settle_where += " AND s.date_to >= %s"
            settle_params.append(start_date)
        if end_date:
            settle_where += " AND s.date_to <= %s"
            settle_params.append(end_date)
        if company and company != "all":
            settle_where += " AND s.company_id = %s"
            settle_params.append(int(company))
        env.cr.execute(f"""
            SELECT s.collector_id,
                   COALESCE(SUM(s.amount_difference), 0) AS difference,
                   COUNT(*) AS qty
            FROM cvi_settlement s
            WHERE {settle_where}
            GROUP BY s.collector_id
            ORDER BY difference
        """, settle_params)
        diff_rows = env.cr.dictfetchall()
        diff_names = self._resolve_names(
            env, "res.users", [r["collector_id"] for r in diff_rows]
        )

        # 5. Mercadería en poder de vendedores.
        env.cr.execute("""
            SELECT q.location_id, COALESCE(SUM(q.quantity), 0) AS qty
            FROM stock_quant q
            JOIN stock_location l ON l.id = q.location_id
            WHERE l.cvi_is_vendor_location AND q.company_id IN %s
            GROUP BY q.location_id
            HAVING SUM(q.quantity) > 0
            ORDER BY qty DESC
            LIMIT 15
        """, [tuple(env.companies.ids)])
        stock_rows = env.cr.dictfetchall()
        location_names = self._resolve_names(
            env, "stock.location", [r["location_id"] for r in stock_rows]
        )

        return {
            "sales_by_vendor": {"labels": periods, "vendors": vendor_series},
            "portfolio_by_collector": {
                "labels": [collector_names.get(i, "N/D") for i in collector_ids],
                "residual": [float(r["residual"]) for r in portfolio_rows],
                "overdue": [float(r["overdue"]) for r in portfolio_rows],
                "collected": [
                    collected_by_collector.get(i, 0.0) for i in collector_ids
                ],
            },
            "aging": {"labels": aging_labels, "values": aging_values},
            "settlement_differences": {
                "labels": [diff_names.get(r["collector_id"], "N/D") for r in diff_rows],
                "values": [float(r["difference"]) for r in diff_rows],
                "counts": [int(r["qty"]) for r in diff_rows],
            },
            "vendor_stock": {
                "labels": [
                    location_names.get(r["location_id"], "N/D") for r in stock_rows
                ],
                "values": [float(r["qty"]) for r in stock_rows],
            },
        }

    def _cvi_map_points(self, env, start_date, end_date, company):
        """Ventas con coordenadas GPS, para el mapa que pide HU-32.

        Solo entran las que tienen ubicación tomada: las cargadas antes de que
        existiera la captura GPS no tienen dónde ubicarse en el mapa.

        El flush_all() es necesario porque la consulta va por SQL crudo: sin él no ve
        lo escrito en la misma transacción. En metrics() funcionaría igual de casualidad,
        porque los KPIs corren antes y ya flushean, pero el método tiene que valer solo.
        """
        env.flush_all()
        where, params = self._cvi_where(env, start_date, end_date, company)
        env.cr.execute(f"""
            SELECT c.id, c.name, c.cvi_latitude, c.cvi_longitude, c.state,
                   c.amount_residual, c.customer_id, c.vendor_id
            FROM cvi_card c
            WHERE {where} AND c.has_geolocation
            LIMIT 1000
        """, params)
        rows = env.cr.dictfetchall()
        customer_names = self._resolve_names(
            env, "cvi.customer", [r["customer_id"] for r in rows]
        )
        vendor_names = self._resolve_names(
            env, "res.users", [r["vendor_id"] for r in rows]
        )
        return [{
            "id": r["id"],
            "name": r["name"],
            "lat": float(r["cvi_latitude"]),
            "lng": float(r["cvi_longitude"]),
            "state": CARD_STATES.get(r["state"], r["state"]),
            "residual": float(r["amount_residual"] or 0),
            "partner": customer_names.get(r["customer_id"], "N/D"),
            "vendor": vendor_names.get(r["vendor_id"], "N/D"),
        } for r in rows]

    @http.route("/collections_from_vendors_installments/filters", type="json", auth="user")
    def filters(self, **kwargs):
        """Metadatos para poblar los selectores del tablero."""
        self._check_access()
        env = request.env
        env.cr.execute("""
            SELECT MIN(date_sale) AS min_date, MAX(date_sale) AS max_date
            FROM cvi_card WHERE company_id IN %s
        """, [tuple(env.companies.ids)])
        dates = env.cr.dictfetchone() or {}
        return {
            "companies": [{"id": c.id, "name": c.display_name} for c in env.companies],
            "min_date": str(dates.get("min_date") or ""),
            "max_date": str(dates.get("max_date") or ""),
        }

    @http.route("/collections_from_vendors_installments/metrics", type="json", auth="user")
    def metrics(self, start_date=None, end_date=None, company="all", **kwargs):
        """KPIs, series de gráficos y puntos del mapa."""
        self._check_access()
        env = request.env
        return {
            "kpis": self._cvi_kpis(env, start_date, end_date, company),
            "charts": self._cvi_charts(env, start_date, end_date, company),
            "map_points": self._cvi_map_points(env, start_date, end_date, company),
        }

    def _cvi_records_domain(self, env, model, start_date, end_date, company, search):
        """Dominio compartido por la tabla paginada y el CSV, para que filtren igual."""
        domain = [("company_id", "in", env.companies.ids)]
        if company and company != "all":
            domain.append(("company_id", "=", int(company)))
        if model == "installments":
            record_model = env["cvi.installment"]
            date_field = "date_due"
        else:
            record_model = env["cvi.card"]
            date_field = "date_sale"
            domain.append(("state", "not in", ("draft", "cancel")))
        if start_date:
            domain.append((date_field, ">=", start_date))
        if end_date:
            domain.append((date_field, "<=", end_date))
        if search:
            domain.append(("customer_id", "ilike", search))
        return domain, record_model, date_field

    @http.route("/collections_from_vendors_installments/records", type="json", auth="user")
    def records(self, model="cards", start_date=None, end_date=None, company="all",
                search=None, page=1, per_page=15, **kwargs):
        """Listado paginado de ventas o cuotas para las pestañas del tablero."""
        self._check_access()
        env = request.env
        page = max(int(page or 1), 1)
        per_page = min(max(int(per_page or 15), 1), 200)
        domain, record_model, date_field = self._cvi_records_domain(
            env, model, start_date, end_date, company, search
        )
        total = record_model.search_count(domain)
        records = record_model.search(
            domain, offset=(page - 1) * per_page, limit=per_page,
            order=f"{date_field} desc",
        )
        return {
            "records": [self._cvi_serialize(r, model) for r in records],
            "page": page,
            "pages": max((total + per_page - 1) // per_page, 1),
            "total": total,
        }

    def _cvi_serialize(self, record, model):
        """Serializa una venta o una cuota para la tabla del tablero."""
        if model == "installments":
            return {
                "id": record.id,
                "partner": record.customer_id.display_name,
                "card": record.card_id.name,
                "sequence": record.sequence,
                "date_due": str(record.date_due or ""),
                "amount": record.amount,
                "paid": record.amount_paid,
                "residual": record.amount_residual,
                "collector": record.collector_id.display_name or "",
                "state": INSTALLMENT_STATES.get(record.state, record.state),
            }
        return {
            "id": record.id,
            "name": record.name,
            "date": str(record.date_sale or ""),
            "partner": record.customer_id.display_name,
            "vendor": record.vendor_id.display_name,
            "collector": record.collector_id.display_name or "",
            "amount_total": record.amount_total,
            "paid": record.amount_paid,
            "residual": record.amount_residual,
            "days_overdue": record.days_overdue,
            "state": CARD_STATES.get(record.state, record.state),
        }

    @http.route("/collections_from_vendors_installments/export", type="http", auth="user")
    def export(self, model="cards", start_date=None, end_date=None, company="all",
               search=None, **kwargs):
        """Exporta el listado filtrado a CSV, sin el tope de página de la tabla.

        El límite de 50000 es un resguardo de memoria, no un tope de negocio.
        """
        self._check_access()
        env = request.env
        domain, record_model, date_field = self._cvi_records_domain(
            env, model, start_date, end_date, company, search
        )
        records = record_model.search(domain, limit=50000, order=f"{date_field} desc")
        rows = [self._cvi_serialize(r, model) for r in records]
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(
                output, fieldnames=list(rows[0].keys()), delimiter=";"
            )
            writer.writeheader()
            writer.writerows(rows)
        filename = f"venta_en_cuotas_{model}.csv"
        return request.make_response(
            output.getvalue().encode("utf-8-sig"),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", f'attachment; filename="{filename}"'),
            ],
        )
