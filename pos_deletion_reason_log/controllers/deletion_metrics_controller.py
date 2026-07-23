# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)


class PosDeletionMetricsController(http.Controller):
    """Endpoints JSON para el dashboard de auditoría de eliminaciones del POS."""

    def _check_access(self):
        if not request.env.user.has_group(
            "pos_deletion_reason_log.group_pos_deletion_audit"
        ):
            raise AccessError("No tienes permisos para ver las métricas de eliminaciones.")

    def _get_timezone(self):
        return request.env.user.tz or "America/Argentina/Buenos_Aires"

    def _get_lang(self):
        return request.env.context.get("lang") or "es_AR"

    def _build_where(
        self, start_date=None, end_date=None, pos="all", cashier="all",
        company="all", dtype="all", reason="all",
    ):
        """WHERE compartido sobre pos_deletion_log (alias dl)."""
        allowed = tuple(request.env.companies.ids) or (0,)
        where = "dl.company_id IN %s"
        params = [allowed]
        tz = self._get_timezone()

        if start_date:
            where += " AND dl.deletion_datetime >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            where += " AND dl.deletion_datetime <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{end_date} 23:59:59", tz])
        if pos and pos != "all":
            where += " AND pc.name = %s"
            params.append(pos)
        if cashier and cashier != "all":
            where += " AND rp.name = %s"
            params.append(cashier)
        if company and company != "all":
            where += " AND rc.name = %s"
            params.append(company)
        if dtype and dtype != "all":
            where += " AND dl.deletion_type = %s"
            params.append(dtype)
        if reason and reason != "all":
            where += " AND COALESCE(pdr.name->>%s, pdr.name->>'en_US') = %s"
            params.extend([self._get_lang(), reason])
        return where, params

    _JOINS = """
        FROM pos_deletion_log dl
        LEFT JOIN pos_config pc ON pc.id = dl.pos_config_id
        LEFT JOIN res_users ru ON ru.id = dl.user_id
        LEFT JOIN res_partner rp ON rp.id = ru.partner_id
        LEFT JOIN res_company rc ON rc.id = dl.company_id
        LEFT JOIN pos_deletion_reason pdr ON pdr.id = dl.reason_id
        LEFT JOIN product_product pp ON pp.id = dl.product_id
        LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
    """

    @http.route("/pos_deletion_metrics/filters", type="json", auth="user")
    def get_filters(self, **kwargs):
        self._check_access()
        cr = request.env.cr
        allowed = tuple(request.env.companies.ids) or (0,)
        lang = self._get_lang()

        cr.execute(
            "SELECT DISTINCT pc.name FROM pos_deletion_log dl "
            "JOIN pos_config pc ON pc.id = dl.pos_config_id "
            "WHERE dl.company_id IN %s AND pc.name IS NOT NULL ORDER BY pc.name",
            [allowed],
        )
        cajas = [r[0] for r in cr.fetchall()]

        cr.execute(
            "SELECT DISTINCT rp.name FROM pos_deletion_log dl "
            "JOIN res_users ru ON ru.id = dl.user_id "
            "JOIN res_partner rp ON rp.id = ru.partner_id "
            "WHERE dl.company_id IN %s AND rp.name IS NOT NULL ORDER BY rp.name",
            [allowed],
        )
        cajeros = [r[0] for r in cr.fetchall()]

        cr.execute(
            "SELECT DISTINCT rc.name FROM pos_deletion_log dl "
            "JOIN res_company rc ON rc.id = dl.company_id "
            "WHERE dl.company_id IN %s AND rc.name IS NOT NULL ORDER BY rc.name",
            [allowed],
        )
        empresas = [r[0] for r in cr.fetchall()]

        cr.execute(
            "SELECT DISTINCT COALESCE(pdr.name->>%s, pdr.name->>'en_US') "
            "FROM pos_deletion_log dl JOIN pos_deletion_reason pdr ON pdr.id = dl.reason_id "
            "WHERE dl.company_id IN %s ORDER BY 1",
            [lang, allowed],
        )
        motivos = [r[0] for r in cr.fetchall() if r[0]]

        return {
            "cajas": cajas,
            "cajeros": cajeros,
            "empresas": empresas,
            "motivos": motivos,
        }

    @http.route("/pos_deletion_metrics/metrics", type="json", auth="user")
    def get_metrics(
        self, start_date=None, end_date=None, pos="all", cashier="all",
        company="all", dtype="all", reason="all", **kwargs
    ):
        self._check_access()
        cr = request.env.cr
        lang = self._get_lang()
        tz = self._get_timezone()
        where, params = self._build_where(
            start_date, end_date, pos, cashier, company, dtype, reason
        )

        # --- KPIs: conteo por tipo, importe y unidades ---
        cr.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE dl.deletion_type = 'order') AS n_order,
                COUNT(*) FILTER (WHERE dl.deletion_type = 'line') AS n_line,
                COUNT(*) FILTER (WHERE dl.deletion_type = 'qty_reduction') AS n_qty,
                COALESCE(SUM(dl.amount_removed), 0) AS amount,
                COALESCE(SUM(dl.qty_removed) FILTER (WHERE dl.deletion_type = 'qty_reduction'), 0) AS units
            {self._JOINS}
            WHERE {where}
            """,
            params,
        )
        row = cr.dictfetchone() or {}
        kpis = {
            "total": int(row.get("total") or 0),
            "n_order": int(row.get("n_order") or 0),
            "n_line": int(row.get("n_line") or 0),
            "n_qty": int(row.get("n_qty") or 0),
            "amount": float(row.get("amount") or 0.0),
            "units": float(row.get("units") or 0.0),
        }

        # --- Tasa de eliminación: órdenes eliminadas / órdenes del período ---
        allowed = tuple(request.env.companies.ids) or (0,)
        ord_where = "po.company_id IN %s AND po.state IN ('paid','done','invoiced')"
        ord_params = [allowed]
        if start_date:
            ord_where += " AND po.date_order >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            ord_params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            ord_where += " AND po.date_order <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            ord_params.extend([f"{end_date} 23:59:59", tz])
        if pos and pos != "all":
            ord_where += " AND pc.name = %s"
            ord_params.append(pos)
        cr.execute(
            f"SELECT COUNT(*) FROM pos_order po LEFT JOIN pos_config pc ON pc.id = po.config_id WHERE {ord_where}",
            ord_params,
        )
        orders_period = int(cr.fetchone()[0] or 0)
        denom = orders_period + kpis["n_order"]
        kpis["deletion_rate"] = round(100.0 * kpis["n_order"] / denom, 2) if denom else 0.0

        # --- Ranking de cajeros (conteo por tipo + importe) ---
        cr.execute(
            f"""
            SELECT rp.name AS cajero,
                COUNT(*) FILTER (WHERE dl.deletion_type = 'order') AS n_order,
                COUNT(*) FILTER (WHERE dl.deletion_type = 'line') AS n_line,
                COUNT(*) FILTER (WHERE dl.deletion_type = 'qty_reduction') AS n_qty,
                COALESCE(SUM(dl.amount_removed), 0) AS amount,
                COUNT(*) AS total
            {self._JOINS}
            WHERE {where}
            GROUP BY rp.name
            ORDER BY total DESC
            LIMIT 15
            """,
            params,
        )
        cashiers = [
            {
                "cajero": r["cajero"] or "—",
                "n_order": int(r["n_order"]),
                "n_line": int(r["n_line"]),
                "n_qty": int(r["n_qty"]),
                "amount": float(r["amount"]),
                "total": int(r["total"]),
            }
            for r in cr.dictfetchall()
        ]

        # --- Distribución por motivo ---
        cr.execute(
            f"""
            SELECT COALESCE(pdr.name->>%s, pdr.name->>'en_US', 'Sin motivo') AS motivo,
                   COUNT(*) AS total
            {self._JOINS}
            WHERE {where}
            GROUP BY 1
            ORDER BY total DESC
            """,
            [lang] + params,
        )
        reasons = [{"motivo": r["motivo"], "total": int(r["total"])} for r in cr.dictfetchall()]

        # --- Tendencia diaria (conteo + importe) en tz del usuario ---
        cr.execute(
            f"""
            SELECT to_char((dl.deletion_datetime AT TIME ZONE 'UTC' AT TIME ZONE %s)::date, 'YYYY-MM-DD') AS dia,
                   COUNT(*) AS total,
                   COALESCE(SUM(dl.amount_removed), 0) AS amount
            {self._JOINS}
            WHERE {where}
            GROUP BY 1
            ORDER BY 1
            """,
            [tz] + params,
        )
        trend = [
            {"dia": r["dia"], "total": int(r["total"]), "amount": float(r["amount"])}
            for r in cr.dictfetchall()
        ]

        # --- Tabla detalle (últimas 500) ---
        cr.execute(
            f"""
            SELECT to_char((dl.deletion_datetime AT TIME ZONE 'UTC' AT TIME ZONE %s), 'YYYY-MM-DD HH24:MI') AS fecha,
                   rp.name AS cajero,
                   dl.deletion_type AS tipo,
                   COALESCE(pt.name->>%s, pt.name->>'en_US', '') AS producto,
                   dl.qty_removed AS qty,
                   dl.amount_removed AS amount,
                   COALESCE(pdr.name->>%s, pdr.name->>'en_US', '') AS motivo,
                   COALESCE(dl.reason_note, '') AS nota,
                   pc.name AS caja
            {self._JOINS}
            WHERE {where}
            ORDER BY dl.deletion_datetime DESC
            LIMIT 500
            """,
            [tz, lang, lang] + params,
        )
        detail = [
            {
                "fecha": r["fecha"],
                "cajero": r["cajero"] or "—",
                "tipo": r["tipo"],
                "producto": r["producto"] or "",
                "qty": float(r["qty"] or 0.0),
                "amount": float(r["amount"] or 0.0),
                "motivo": r["motivo"] or "",
                "nota": r["nota"] or "",
                "caja": r["caja"] or "",
            }
            for r in cr.dictfetchall()
        ]

        return {
            "kpis": kpis,
            "cashiers": cashiers,
            "reasons": reasons,
            "trend": trend,
            "detail": detail,
        }
