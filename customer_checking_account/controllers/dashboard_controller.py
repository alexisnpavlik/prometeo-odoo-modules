# -*- coding: utf-8 -*-
import csv
import io
import json
import logging
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)

INSTALLMENT_STATES = {
    "pending": "Pendiente",
    "partial": "Parcial",
    "paid": "Pagada",
    "overdue": "Vencida",
}

PAYMENT_METHODS = {
    "cash": "Efectivo",
    "transfer": "Transferencia",
    "card": "Tarjeta",
    "other": "Otro",
}

WITHDRAWAL_STATES = {
    "draft": "Borrador",
    "pending": "Pendiente",
    "partial": "Pago parcial",
    "paid": "Pagado",
    "cancel": "Cancelado",
}


def _to_ids(value):
    """Ids de un filtro multi-selección: lista, JSON (export), id suelto o "all" (= sin filtro)."""
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                value = json.loads(value)
            except ValueError:
                return []
        elif value in ("", "all"):
            return []
        else:
            value = [value]
    elif not isinstance(value, (list, tuple)):
        value = [value] if value else []
    ids = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


class CcaDashboardController(http.Controller):

    def _check_access(self, env=None):
        """Valida que el usuario pertenezca al grupo Manager de Cuenta Corriente."""
        env = env or request.env
        if not env.user.has_group("customer_checking_account.group_cca_user"):
            raise AccessError("No tenés permisos para acceder al dashboard de cuenta corriente.")

    def _cca_where(self, env, start_date, end_date, company, partner, alias="w"):
        """WHERE parametrizado sobre cca_withdrawal (alias `w`), scopeado a las compañías."""
        where = f"{alias}.state NOT IN ('draft', 'cancel') AND {alias}.company_id IN %s"
        params = [tuple(env.companies.ids)]
        if start_date:
            where += f" AND {alias}.date >= %s"
            params.append(start_date)
        if end_date:
            where += f" AND {alias}.date <= %s"
            params.append(end_date)
        if _to_ids(company):
            where += f" AND {alias}.company_id IN %s"
            params.append(tuple(_to_ids(company)))
        if _to_ids(partner):
            where += f" AND {alias}.partner_id IN %s"
            params.append(tuple(_to_ids(partner)))
        return where, params

    def _cca_kpis(self, env, start_date, end_date, company, partner):
        """Calcula los KPIs de la cartera de fiados en el período."""
        env.flush_all()
        where, params = self._cca_where(env, start_date, end_date, company, partner)
        env.cr.execute(f"""
            SELECT COUNT(*) AS withdrawal_count,
                   COALESCE(SUM(w.amount_total), 0) AS total_withdrawn
            FROM cca_withdrawal w
            WHERE {where}
        """, params)
        row = env.cr.dictfetchone() or {}

        env.cr.execute(f"""
            SELECT COALESCE(SUM(i.amount_residual), 0) AS total_balance,
                   COALESCE(SUM(i.amount_residual) FILTER (
                       WHERE i.date_due < CURRENT_DATE AND i.amount_residual > 0
                   ), 0) AS overdue_balance,
                   COUNT(*) FILTER (
                       WHERE i.date_due < CURRENT_DATE AND i.amount_residual > 0
                   ) AS overdue_installments,
                   COUNT(*) AS installment_count
            FROM cca_installment i
            JOIN cca_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
        """, params)
        balances = env.cr.dictfetchone() or {}

        credit_params = [tuple(env.companies.ids)]
        credit_where = "p.state = 'posted' AND p.company_id IN %s"
        if start_date:
            credit_where += " AND p.date >= %s"
            credit_params.append(start_date)
        if end_date:
            credit_where += " AND p.date <= %s"
            credit_params.append(end_date)
        if _to_ids(company):
            credit_where += " AND p.company_id IN %s"
            credit_params.append(tuple(_to_ids(company)))
        if _to_ids(partner):
            credit_where += " AND p.partner_id IN %s"
            credit_params.append(tuple(_to_ids(partner)))
        env.cr.execute(f"""
            SELECT COALESCE(SUM(p.amount_unallocated), 0) AS credit_balance,
                   COALESCE(SUM(p.amount), 0) AS collected
            FROM cca_payment p
            WHERE {credit_where}
        """, credit_params)
        payments = env.cr.dictfetchone() or {}

        installment_count = balances.get("installment_count") or 0
        overdue_installments = balances.get("overdue_installments") or 0
        return {
            "total_balance": float(balances.get("total_balance") or 0),
            "overdue_balance": float(balances.get("overdue_balance") or 0),
            "credit_balance": float(payments.get("credit_balance") or 0),
            "total_withdrawn": float(row.get("total_withdrawn") or 0),
            "withdrawal_count": int(row.get("withdrawal_count") or 0),
            "overdue_installments": int(overdue_installments),
            "overdue_rate": round(overdue_installments / installment_count * 100, 1)
                            if installment_count else 0.0,
            "collected": float(payments.get("collected") or 0),
        }

    def _cca_charts(self, env, start_date, end_date, company, partner):
        """Arma las series de los cinco gráficos del dashboard."""
        env.flush_all()
        where, params = self._cca_where(env, start_date, end_date, company, partner)

        env.cr.execute(f"""
            SELECT to_char(date_trunc('month', w.date), 'YYYY-MM') AS period,
                   w.company_id,
                   COALESCE(SUM(i.amount_residual), 0) AS residual
            FROM cca_installment i
            JOIN cca_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY period, w.company_id
            ORDER BY period
        """, params)
        trend_rows = env.cr.dictfetchall()
        company_names = self._resolve_names(env, "res.company", [r["company_id"] for r in trend_rows])
        labels = sorted({r["period"] for r in trend_rows})
        companies_series = {}
        for row in trend_rows:
            name = company_names.get(row["company_id"], "N/D")
            series = companies_series.setdefault(name, [0.0] * len(labels))
            series[labels.index(row["period"])] = float(row["residual"])

        env.cr.execute(f"""
            SELECT to_char(date_trunc('month', i.date_due), 'YYYY-MM') AS period,
                   COALESCE(SUM(i.amount_allocated), 0) AS collected,
                   COALESCE(SUM(i.amount_residual) FILTER (
                       WHERE i.date_due < CURRENT_DATE
                   ), 0) AS overdue
            FROM cca_installment i
            JOIN cca_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY period
            ORDER BY period
        """, params)
        vs_rows = env.cr.dictfetchall()

        env.cr.execute(f"""
            SELECT i.state, COUNT(*) AS qty
            FROM cca_installment i
            JOIN cca_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY i.state
        """, params)
        # Orden fijo de estados: el color de cada uno no depende del orden del GROUP BY.
        order = list(INSTALLMENT_STATES)
        status_rows = sorted(
            env.cr.dictfetchall(),
            key=lambda r: order.index(r["state"]) if r["state"] in order else len(order),
        )

        env.cr.execute(f"""
            SELECT w.partner_id, COALESCE(SUM(i.amount_residual), 0) AS residual
            FROM cca_installment i
            JOIN cca_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY w.partner_id
            HAVING SUM(i.amount_residual) > 0
            ORDER BY residual DESC
            LIMIT 10
        """, params)
        top_rows = env.cr.dictfetchall()
        partner_names = self._resolve_names(env, "res.partner", [r["partner_id"] for r in top_rows])

        today = fields.Date.context_today(env.user)
        upcoming = self._cca_upcoming(env, company, partner, today)
        aging = self._cca_aging(env, company, partner, today)
        by_method = self._cca_by_method(env, start_date, end_date, company, partner)

        return {
            "upcoming": upcoming,
            "aging": aging,
            "by_method": by_method,
            "balance_trend": {"labels": labels, "companies": companies_series},
            "collected_vs_overdue": {
                "labels": [r["period"] for r in vs_rows],
                "collected": [float(r["collected"]) for r in vs_rows],
                "overdue": [float(r["overdue"]) for r in vs_rows],
            },
            "installment_status": {
                "keys": [r["state"] for r in status_rows],
                "labels": [INSTALLMENT_STATES.get(r["state"], r["state"]) for r in status_rows],
                "values": [int(r["qty"]) for r in status_rows],
            },
            "top_partners": {
                "labels": [partner_names.get(r["partner_id"], "N/D") for r in top_rows],
                "values": [float(r["residual"]) for r in top_rows],
            },
        }

    def _cca_upcoming(self, env, company, partner, today, weeks=8):
        """Cobranza próxima: residual vencido y lo que vence en cada una de las próximas semanas.

        No usa el rango de fechas del filtro: mira hacia adelante desde hoy.
        """
        where, params = self._cca_where(env, None, None, company, partner)
        end = today + timedelta(days=7 * weeks)
        env.cr.execute(f"""
            SELECT i.date_due, i.amount_residual
            FROM cca_installment i
            JOIN cca_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where} AND i.amount_residual > 0 AND i.date_due < %s
        """, params + [end])
        values = [0.0] * (weeks + 1)
        for date_due, residual in env.cr.fetchall():
            index = 0 if date_due < today else 1 + (date_due - today).days // 7
            values[index] += float(residual)
        labels = ["Vencido"] + [
            (today + timedelta(days=7 * week)).strftime("%d/%m") for week in range(weeks)
        ]
        return {"labels": labels, "values": [round(v, 2) for v in values]}

    def _cca_aging(self, env, company, partner, today):
        """Antigüedad de la deuda vencida por tramos de días."""
        where, params = self._cca_where(env, None, None, company, partner)
        env.cr.execute(f"""
            SELECT i.date_due, i.amount_residual
            FROM cca_installment i
            JOIN cca_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where} AND i.amount_residual > 0 AND i.date_due < %s
        """, params + [today])
        values = [0.0, 0.0, 0.0, 0.0]
        for date_due, residual in env.cr.fetchall():
            days = (today - date_due).days
            index = 0 if days <= 30 else 1 if days <= 60 else 2 if days <= 90 else 3
            values[index] += float(residual)
        return {
            "labels": ["1-30 días", "31-60 días", "61-90 días", "Más de 90 días"],
            "values": [round(v, 2) for v in values],
        }

    def _cca_by_method(self, env, start_date, end_date, company, partner):
        """Cobrado por mes y medio de pago (pagos vigentes)."""
        where = "p.state = 'posted' AND p.company_id IN %s"
        params = [tuple(env.companies.ids)]
        if start_date:
            where += " AND p.date >= %s"
            params.append(start_date)
        if end_date:
            where += " AND p.date <= %s"
            params.append(end_date)
        if _to_ids(company):
            where += " AND p.company_id IN %s"
            params.append(tuple(_to_ids(company)))
        if _to_ids(partner):
            where += " AND p.partner_id IN %s"
            params.append(tuple(_to_ids(partner)))
        env.cr.execute(f"""
            SELECT to_char(date_trunc('month', p.date), 'YYYY-MM') AS period,
                   p.payment_method, COALESCE(SUM(p.amount), 0) AS total
            FROM cca_payment p
            WHERE {where}
            GROUP BY period, p.payment_method
            ORDER BY period
        """, params)
        rows = env.cr.dictfetchall()
        labels = sorted({r["period"] for r in rows})
        series = []
        for key, label in PAYMENT_METHODS.items():
            totals = {r["period"]: float(r["total"]) for r in rows if r["payment_method"] == key}
            if totals:
                series.append({"key": key, "label": label, "values": [totals.get(l, 0.0) for l in labels]})
        return {"labels": labels, "series": series}

    def _resolve_names(self, env, model, ids):
        """Resuelve {id: display_name} vía ORM con sudo, evitando SQL sobre columnas jsonb."""
        ids = [i for i in set(ids) if i]
        if not ids:
            return {}
        return {rec.id: rec.display_name for rec in env[model].sudo().browse(ids)}

    def _cca_partners(self, env):
        """Contactos con cuenta corriente en las compañías del usuario, para el filtro."""
        env.cr.execute("""
            SELECT DISTINCT partner_id FROM cca_account WHERE company_id IN %s
        """, [tuple(env.companies.ids)])
        partner_ids = [r["partner_id"] for r in env.cr.dictfetchall()]
        partner_names = self._resolve_names(env, "res.partner", partner_ids)
        return sorted(
            ({"id": pid, "name": name} for pid, name in partner_names.items()),
            key=lambda p: p["name"],
        )

    @http.route("/customer_checking_account/filters", type="json", auth="user")
    def filters(self, **kwargs):
        """Metadatos para poblar los selectores del dashboard."""
        self._check_access()
        env = request.env
        env.cr.execute("""
            SELECT MIN(date) AS min_date, MAX(date) AS max_date
            FROM cca_withdrawal WHERE company_id IN %s
        """, [tuple(env.companies.ids)])
        dates = env.cr.dictfetchone() or {}
        return {
            "companies": [
                {"id": c.id, "name": c.display_name} for c in env.companies
            ],
            "partners": self._cca_partners(env),
            "min_date": str(dates.get("min_date") or ""),
            "max_date": str(dates.get("max_date") or ""),
        }

    @http.route("/customer_checking_account/metrics", type="json", auth="user")
    def metrics(self, start_date=None, end_date=None, company="all", partner="all", **kwargs):
        """KPIs y series de gráficos del dashboard."""
        self._check_access()
        env = request.env
        return {
            "kpis": self._cca_kpis(env, start_date, end_date, company, partner),
            "charts": self._cca_charts(env, start_date, end_date, company, partner),
        }

    def _cca_records_domain(self, env, model, start_date, end_date, company, partner, search):
        """Arma el dominio y resuelve el modelo/campo de fecha para retiros o cuotas.

        Compartido por `records()` (paginado, para la tabla del dashboard) y `export()`
        (sin cap de página, para el CSV) para que ambos filtren exactamente igual.
        """
        domain = [("company_id", "in", env.companies.ids)]
        if _to_ids(company):
            domain.append(("company_id", "in", _to_ids(company)))
        if _to_ids(partner):
            domain.append(("partner_id", "in", _to_ids(partner)))
        if model == "installments":
            record_model = env["cca.installment"]
            date_field = "date_due"
        else:
            record_model = env["cca.withdrawal"]
            date_field = "date"
            domain.append(("state", "not in", ("draft", "cancel")))
        if start_date:
            domain.append((date_field, ">=", start_date))
        if end_date:
            domain.append((date_field, "<=", end_date))
        if search:
            domain.append(("partner_id", "ilike", search))
        return domain, record_model, date_field

    @http.route("/customer_checking_account/records", type="json", auth="user")
    def records(self, model="withdrawals", start_date=None, end_date=None, company="all",
                partner="all", search=None, page=1, per_page=15, **kwargs):
        """Listado paginado de retiros o cuotas para las pestañas del dashboard."""
        self._check_access()
        env = request.env
        page = max(int(page or 1), 1)
        per_page = min(max(int(per_page or 15), 1), 200)
        domain, record_model, date_field = self._cca_records_domain(
            env, model, start_date, end_date, company, partner, search
        )
        total = record_model.search_count(domain)
        records = record_model.search(
            domain, offset=(page - 1) * per_page, limit=per_page, order=f"{date_field} desc"
        )
        return {
            "records": [self._cca_serialize(record, model) for record in records],
            "page": page,
            "pages": max((total + per_page - 1) // per_page, 1),
            "total": total,
        }

    def _cca_serialize(self, record, model):
        """Serializa un retiro o una cuota para la tabla del dashboard."""
        if model == "installments":
            return {
                "id": record.id,
                "partner": record.partner_id.display_name,
                "withdrawal": record.withdrawal_id.name,
                "sequence": record.sequence,
                "date_due": str(record.date_due or ""),
                "amount": record.amount,
                "allocated": record.amount_allocated,
                "residual": record.amount_residual,
                "state": INSTALLMENT_STATES.get(record.state, record.state),
                "state_key": record.state,
            }
        return {
            "id": record.id,
            "name": record.name,
            "date": str(record.date or ""),
            "partner": record.partner_id.display_name,
            "company": record.company_id.display_name,
            "amount_total": record.amount_total,
            "residual": record.amount_residual,
            "overdue": record.is_overdue,
            "state": WITHDRAWAL_STATES.get(record.state, record.state),
            "state_key": record.state,
        }

    @http.route("/customer_checking_account/export", type="http", auth="user")
    def export(self, model="withdrawals", start_date=None, end_date=None, company="all",
               partner="all", search=None, **kwargs):
        """Exporta el listado filtrado a CSV, sin el cap de 200 filas que usa la tabla del
        dashboard (esa paginación es solo para la UI). El límite de 50000 es un resguardo
        de memoria, no un tope de negocio: en la práctica ninguna cartera lo alcanza."""
        self._check_access()
        env = request.env
        domain, record_model, date_field = self._cca_records_domain(
            env, model, start_date, end_date, company, partner, search
        )
        records = record_model.search(domain, limit=50000, order=f"{date_field} desc")
        rows = [self._cca_serialize(record, model) for record in records]
        output = io.StringIO()
        if rows:
            fieldnames = [k for k in rows[0].keys() if not k.endswith("_key")]
            writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        filename = f"cuenta_corriente_{model}.csv"
        return request.make_response(
            output.getvalue().encode("utf-8-sig"),
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", f'attachment; filename="{filename}"'),
            ],
        )
