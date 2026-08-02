# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)


class PosControlMetricsController(http.Controller):
    """Endpoints JSON para el dashboard de trazabilidad de operaciones POS."""

    def _check_access(self):
        if not request.env.user.has_group(
            "pos_deletion_reason_log.group_pos_deletion_audit"
        ):
            raise AccessError("No tienes permisos para ver las métricas de trazabilidad.")

    def _get_timezone(self):
        return request.env.user.tz or "America/Argentina/Buenos_Aires"

    def _get_lang(self):
        return request.env.context.get("lang") or "es_AR"

    def _build_where(
        self, start_date=None, end_date=None, pos="all", cashier="all",
        company="all", dtype="all",
    ):
        """WHERE compartido sobre pos_control_log (alias dl)."""
        allowed = tuple(request.env.companies.ids) or (0,)
        where = "dl.company_id IN %s"
        params = [allowed]
        tz = self._get_timezone()

        if start_date:
            where += " AND dl.event_datetime >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            where += " AND dl.event_datetime <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
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
            where += " AND dl.event_type = %s"
            params.append(dtype)
        return where, params

    _JOINS = """
        FROM pos_control_log dl
        LEFT JOIN pos_config pc ON pc.id = dl.pos_config_id
        LEFT JOIN res_users ru ON ru.id = dl.user_id
        LEFT JOIN res_partner rp ON rp.id = ru.partner_id
        LEFT JOIN res_company rc ON rc.id = dl.company_id
        LEFT JOIN pos_deletion_reason pdr ON pdr.id = dl.reason_id
        LEFT JOIN product_product pp ON pp.id = dl.product_id
        LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
    """

    # Los reembolsos no se registran en el log de control: Odoo ya los persiste
    # nativamente como líneas con refunded_orderline_id y qty negativa. Se leen
    # directo de pos_order_line, así se capturan TODOS (históricos y futuros) y
    # no hay forma de evadir el conteo desde el POS.
    _REFUND_JOINS = """
        FROM pos_order_line pol
        JOIN pos_order po ON po.id = pol.order_id
        LEFT JOIN pos_config pc ON pc.id = po.config_id
        LEFT JOIN res_users ru ON ru.id = po.user_id
        LEFT JOIN res_partner rp ON rp.id = ru.partner_id
        LEFT JOIN res_company rc ON rc.id = po.company_id
        LEFT JOIN product_product pp ON pp.id = pol.product_id
        LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
    """

    def _build_refund_where(
        self, start_date=None, end_date=None, pos="all", cashier="all",
        company="all",
    ):
        """WHERE para las líneas de reembolso (alias pol / po). Solo órdenes
        no canceladas; misma semántica de filtros que el log de control."""
        allowed = tuple(request.env.companies.ids) or (0,)
        where = (
            "pol.refunded_orderline_id IS NOT NULL "
            "AND po.company_id IN %s "
            "AND po.state IN ('paid','done','invoiced')"
        )
        params = [allowed]
        tz = self._get_timezone()

        if start_date:
            where += " AND po.date_order >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
            params.extend([f"{start_date} 00:00:00", tz])
        if end_date:
            where += " AND po.date_order <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
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
        return where, params

    @http.route("/pos_control_metrics/filters", type="json", auth="user")
    def get_filters(self, **kwargs):
        self._check_access()
        cr = request.env.cr
        allowed = tuple(request.env.companies.ids) or (0,)

        cr.execute(
            "SELECT DISTINCT pc.name FROM pos_control_log dl "
            "JOIN pos_config pc ON pc.id = dl.pos_config_id "
            "WHERE dl.company_id IN %s AND pc.name IS NOT NULL ORDER BY pc.name",
            [allowed],
        )
        cajas = [r[0] for r in cr.fetchall()]

        cr.execute(
            "SELECT DISTINCT rp.name FROM pos_control_log dl "
            "JOIN res_users ru ON ru.id = dl.user_id "
            "JOIN res_partner rp ON rp.id = ru.partner_id "
            "WHERE dl.company_id IN %s AND rp.name IS NOT NULL ORDER BY rp.name",
            [allowed],
        )
        cajeros = [r[0] for r in cr.fetchall()]

        cr.execute(
            "SELECT DISTINCT rc.name FROM pos_control_log dl "
            "JOIN res_company rc ON rc.id = dl.company_id "
            "WHERE dl.company_id IN %s AND rc.name IS NOT NULL ORDER BY rc.name",
            [allowed],
        )
        empresas = [r[0] for r in cr.fetchall()]

        return {
            "cajas": cajas,
            "cajeros": cajeros,
            "empresas": empresas,
        }

    @http.route("/pos_control_metrics/metrics", type="json", auth="user")
    def get_metrics(
        self, start_date=None, end_date=None, pos="all", cashier="all",
        company="all", dtype="all", **kwargs
    ):
        self._check_access()
        cr = request.env.cr
        lang = self._get_lang()
        tz = self._get_timezone()
        where, params = self._build_where(
            start_date, end_date, pos, cashier, company, dtype
        )
        # Los reembolsos entran cuando no se filtra por un tipo puntual del log
        # ("Todos") o cuando se pide expresamente el tipo "refund".
        include_refunds = dtype in ("all", "refund")

        # --- KPIs: conteo por tipo, importe y unidades ---
        cr.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE dl.event_type = 'order') AS n_order,
                COUNT(*) FILTER (WHERE dl.event_type = 'line') AS n_line,
                COUNT(*) FILTER (WHERE dl.event_type = 'qty_reduction') AS n_qty,
                COUNT(*) FILTER (WHERE dl.event_type = 'high_discount') AS n_discount,
                COUNT(*) FILTER (WHERE dl.event_type = 'price_reduction') AS n_price,
                COUNT(*) FILTER (WHERE dl.event_type = 'price_increase') AS n_price_up,
                COALESCE(SUM(dl.amount_removed), 0) AS amount,
                COALESCE(SUM(dl.qty_removed) FILTER (WHERE dl.event_type = 'qty_reduction'), 0) AS units,
                COALESCE(AVG(dl.discount_percent) FILTER (WHERE dl.event_type = 'high_discount'), 0) AS avg_discount
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
            "n_discount": int(row.get("n_discount") or 0),
            "n_price": int(row.get("n_price") or 0),
            "n_price_up": int(row.get("n_price_up") or 0),
            "amount": float(row.get("amount") or 0.0),
            "units": float(row.get("units") or 0.0),
            "avg_discount": round(float(row.get("avg_discount") or 0.0), 2),
            "n_refund": 0,
            "refund_amount": 0.0,
            "refund_units": 0.0,
        }

        # --- KPIs de reembolsos (fuente nativa pos_order_line) ---
        rf_where, rf_params = self._build_refund_where(
            start_date, end_date, pos, cashier, company
        )
        if include_refunds:
            cr.execute(
                f"""
                SELECT
                    COUNT(DISTINCT po.id) AS n_refund,
                    COALESCE(ABS(SUM(pol.price_subtotal_incl)), 0) AS refund_amount,
                    COALESCE(ABS(SUM(pol.qty)), 0) AS refund_units
                {self._REFUND_JOINS}
                WHERE {rf_where}
                """,
                rf_params,
            )
            rf_row = cr.dictfetchone() or {}
            kpis["n_refund"] = int(rf_row.get("n_refund") or 0)
            kpis["refund_amount"] = float(rf_row.get("refund_amount") or 0.0)
            kpis["refund_units"] = float(rf_row.get("refund_units") or 0.0)

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
        # Se arma como dict por nombre para poder fusionar los reembolsos
        # (fuente distinta) y no perder cajeros que solo hicieron reembolsos.
        cr.execute(
            f"""
            SELECT rp.name AS cajero,
                COUNT(*) FILTER (WHERE dl.event_type = 'order') AS n_order,
                COUNT(*) FILTER (WHERE dl.event_type = 'line') AS n_line,
                COUNT(*) FILTER (WHERE dl.event_type = 'qty_reduction') AS n_qty,
                COUNT(*) FILTER (WHERE dl.event_type = 'high_discount') AS n_discount,
                COUNT(*) FILTER (WHERE dl.event_type = 'price_reduction') AS n_price,
                COUNT(*) FILTER (WHERE dl.event_type = 'price_increase') AS n_price_up,
                COALESCE(SUM(dl.amount_removed), 0) AS amount,
                COUNT(*) AS total
            {self._JOINS}
            WHERE {where}
            GROUP BY rp.name
            """,
            params,
        )
        cashier_map = {}
        for r in cr.dictfetchall():
            name = r["cajero"] or "—"
            cashier_map[name] = {
                "cajero": name,
                "n_order": int(r["n_order"]),
                "n_line": int(r["n_line"]),
                "n_qty": int(r["n_qty"]),
                "n_discount": int(r["n_discount"]),
                "n_price": int(r["n_price"]),
                "n_price_up": int(r["n_price_up"]),
                "amount": float(r["amount"]),
                "total": int(r["total"]),
                "n_refund": 0,
                "refund_amount": 0.0,
            }

        if include_refunds:
            cr.execute(
                f"""
                SELECT rp.name AS cajero,
                       COUNT(DISTINCT po.id) AS n_refund,
                       COALESCE(ABS(SUM(pol.price_subtotal_incl)), 0) AS refund_amount
                {self._REFUND_JOINS}
                WHERE {rf_where}
                GROUP BY rp.name
                """,
                rf_params,
            )
            for r in cr.dictfetchall():
                name = r["cajero"] or "—"
                entry = cashier_map.get(name)
                if not entry:
                    entry = {
                        "cajero": name, "n_order": 0, "n_line": 0, "n_qty": 0,
                        "n_discount": 0, "n_price": 0, "n_price_up": 0,
                        "amount": 0.0, "total": 0, "n_refund": 0, "refund_amount": 0.0,
                    }
                    cashier_map[name] = entry
                entry["n_refund"] = int(r["n_refund"])
                entry["refund_amount"] = float(r["refund_amount"])

        cashiers = sorted(
            cashier_map.values(),
            key=lambda c: c["total"] + c["n_refund"],
            reverse=True,
        )[:15]

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
            SELECT to_char((dl.event_datetime AT TIME ZONE 'UTC' AT TIME ZONE %s)::date, 'YYYY-MM-DD') AS dia,
                   COUNT(*) AS total,
                   COALESCE(SUM(dl.amount_removed), 0) AS amount
            {self._JOINS}
            WHERE {where}
            GROUP BY 1
            ORDER BY 1
            """,
            [tz] + params,
        )
        trend_map = {
            r["dia"]: {
                "dia": r["dia"], "total": int(r["total"]),
                "amount": float(r["amount"]), "n_refund": 0,
            }
            for r in cr.dictfetchall()
        }

        if include_refunds:
            cr.execute(
                f"""
                SELECT to_char((po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date, 'YYYY-MM-DD') AS dia,
                       COUNT(DISTINCT po.id) AS n_refund
                {self._REFUND_JOINS}
                WHERE {rf_where}
                GROUP BY 1
                """,
                [tz] + rf_params,
            )
            for r in cr.dictfetchall():
                entry = trend_map.get(r["dia"])
                if not entry:
                    entry = {"dia": r["dia"], "total": 0, "amount": 0.0, "n_refund": 0}
                    trend_map[r["dia"]] = entry
                entry["n_refund"] = int(r["n_refund"])

        trend = [trend_map[k] for k in sorted(trend_map)]

        # --- Tabla detalle (últimos 500) ---
        cr.execute(
            f"""
            SELECT to_char((dl.event_datetime AT TIME ZONE 'UTC' AT TIME ZONE %s), 'YYYY-MM-DD HH24:MI') AS fecha,
                   rp.name AS cajero,
                   dl.event_type AS tipo,
                   COALESCE(pt.name->>%s, pt.name->>'en_US', '') AS producto,
                   dl.qty_removed AS qty,
                   dl.discount_percent AS discount,
                   dl.old_price AS old_price,
                   dl.new_price AS new_price,
                   dl.amount_removed AS amount,
                   COALESCE(pdr.name->>%s, pdr.name->>'en_US', '') AS motivo,
                   COALESCE(dl.reason_note, '') AS nota,
                   pc.name AS caja
            {self._JOINS}
            WHERE {where}
            ORDER BY dl.event_datetime DESC
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
                "discount": float(r["discount"] or 0.0),
                "old_price": float(r["old_price"] or 0.0),
                "new_price": float(r["new_price"] or 0.0),
                "amount": float(r["amount"] or 0.0),
                "motivo": r["motivo"] or "",
                "nota": r["nota"] or "",
                "caja": r["caja"] or "",
            }
            for r in cr.dictfetchall()
        ]

        # Filas de reembolso (fuente nativa) mezcladas en el mismo detalle.
        if include_refunds:
            cr.execute(
                f"""
                SELECT to_char((po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s), 'YYYY-MM-DD HH24:MI') AS fecha,
                       rp.name AS cajero,
                       COALESCE(pt.name->>%s, pt.name->>'en_US', '') AS producto,
                       pol.qty AS qty,
                       pol.price_subtotal_incl AS amount,
                       COALESCE(po.pos_reference, po.name, '') AS nota,
                       pc.name AS caja
                {self._REFUND_JOINS}
                WHERE {rf_where}
                ORDER BY po.date_order DESC
                LIMIT 500
                """,
                [tz, lang] + rf_params,
            )
            for r in cr.dictfetchall():
                detail.append({
                    "fecha": r["fecha"],
                    "cajero": r["cajero"] or "—",
                    "tipo": "refund",
                    "producto": r["producto"] or "",
                    "qty": float(r["qty"] or 0.0),
                    "discount": 0.0,
                    "old_price": 0.0,
                    "new_price": 0.0,
                    "amount": float(r["amount"] or 0.0),
                    "motivo": "",
                    "nota": r["nota"] or "",
                    "caja": r["caja"] or "",
                })
            # El formato 'YYYY-MM-DD HH24:MI' ordena cronológicamente como texto.
            detail.sort(key=lambda d: d["fecha"] or "", reverse=True)
            detail = detail[:500]

        return {
            "kpis": kpis,
            "cashiers": cashiers,
            "reasons": reasons,
            "trend": trend,
            "detail": detail,
        }
