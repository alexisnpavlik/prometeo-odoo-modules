# -*- coding: utf-8 -*-
import csv
import io
import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)

INSTALLMENT_STATES = {
    "pending": "Pendiente",
    "partial": "Parcial",
    "paid": "Pagada",
    "overdue": "Vencida",
}

WITHDRAWAL_STATES = {
    "draft": "Borrador",
    "pending": "Pendiente",
    "partial": "Pago parcial",
    "paid": "Pagado",
    "cancel": "Cancelado",
}


class CawDashboardController(http.Controller):

    def _check_access(self, env=None):
        """Valida que el usuario pertenezca al grupo Manager de Cuenta Corriente."""
        env = env or request.env
        if not env.user.has_group("checking_account_withdrawals.group_cc_manager"):
            raise AccessError("No tenés permisos para acceder al dashboard de cuenta corriente.")

    def _caw_where(self, env, start_date, end_date, company, partner, alias="w"):
        """WHERE parametrizado sobre caw_withdrawal (alias `w`), scopeado a las compañías."""
        where = f"{alias}.state NOT IN ('draft', 'cancel') AND {alias}.company_id IN %s"
        params = [tuple(env.companies.ids)]
        if start_date:
            where += f" AND {alias}.date >= %s"
            params.append(start_date)
        if end_date:
            where += f" AND {alias}.date <= %s"
            params.append(end_date)
        if company and company != "all":
            where += f" AND {alias}.company_id = %s"
            params.append(int(company))
        if partner and partner != "all":
            where += f" AND {alias}.partner_id = %s"
            params.append(int(partner))
        return where, params

    def _caw_kpis(self, env, start_date, end_date, company, partner):
        """Calcula los KPIs de la cartera de fiados en el período."""
        env.flush_all()
        where, params = self._caw_where(env, start_date, end_date, company, partner)
        env.cr.execute(f"""
            SELECT COUNT(*) AS withdrawal_count,
                   COALESCE(SUM(w.amount_total), 0) AS total_withdrawn
            FROM caw_withdrawal w
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
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
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
        if company and company != "all":
            credit_where += " AND p.company_id = %s"
            credit_params.append(int(company))
        if partner and partner != "all":
            credit_where += " AND p.partner_id = %s"
            credit_params.append(int(partner))
        env.cr.execute(f"""
            SELECT COALESCE(SUM(p.amount_unallocated), 0) AS credit_balance,
                   COALESCE(SUM(p.amount), 0) AS collected
            FROM caw_payment p
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

    def _caw_charts(self, env, start_date, end_date, company, partner):
        """Arma las series de los cinco gráficos del dashboard."""
        env.flush_all()
        where, params = self._caw_where(env, start_date, end_date, company, partner)

        env.cr.execute(f"""
            SELECT to_char(date_trunc('month', w.date), 'YYYY-MM') AS period,
                   w.company_id,
                   COALESCE(SUM(i.amount_residual), 0) AS residual
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
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
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY period
            ORDER BY period
        """, params)
        vs_rows = env.cr.dictfetchall()

        env.cr.execute(f"""
            SELECT i.state, COUNT(*) AS qty
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY i.state
        """, params)
        status_rows = env.cr.dictfetchall()

        env.cr.execute(f"""
            SELECT w.partner_id, COALESCE(SUM(i.amount_residual), 0) AS residual
            FROM caw_installment i
            JOIN caw_withdrawal w ON w.id = i.withdrawal_id
            WHERE {where}
            GROUP BY w.partner_id
            HAVING SUM(i.amount_residual) > 0
            ORDER BY residual DESC
            LIMIT 10
        """, params)
        top_rows = env.cr.dictfetchall()
        partner_names = self._resolve_names(env, "res.partner", [r["partner_id"] for r in top_rows])

        env.cr.execute(f"""
            SELECT w.company_id, COALESCE(SUM(w.amount_total), 0) AS total
            FROM caw_withdrawal w
            WHERE {where}
            GROUP BY w.company_id
            ORDER BY total DESC
        """, params)
        company_rows = env.cr.dictfetchall()

        return {
            "balance_trend": {"labels": labels, "companies": companies_series},
            "collected_vs_overdue": {
                "labels": [r["period"] for r in vs_rows],
                "collected": [float(r["collected"]) for r in vs_rows],
                "overdue": [float(r["overdue"]) for r in vs_rows],
            },
            "installment_status": {
                "labels": [INSTALLMENT_STATES.get(r["state"], r["state"]) for r in status_rows],
                "values": [int(r["qty"]) for r in status_rows],
            },
            "top_partners": {
                "labels": [partner_names.get(r["partner_id"], "N/D") for r in top_rows],
                "values": [float(r["residual"]) for r in top_rows],
            },
            "by_company": {
                "labels": [company_names.get(r["company_id"], "N/D") for r in company_rows],
                "values": [float(r["total"]) for r in company_rows],
            },
        }

    def _resolve_names(self, env, model, ids):
        """Resuelve {id: display_name} vía ORM con sudo, evitando SQL sobre columnas jsonb."""
        ids = [i for i in set(ids) if i]
        if not ids:
            return {}
        return {rec.id: rec.display_name for rec in env[model].sudo().browse(ids)}

    def _caw_partners(self, env):
        """Contactos con cuenta corriente en las compañías del usuario, para el filtro."""
        env.cr.execute("""
            SELECT DISTINCT partner_id FROM caw_account WHERE company_id IN %s
        """, [tuple(env.companies.ids)])
        partner_ids = [r["partner_id"] for r in env.cr.dictfetchall()]
        partner_names = self._resolve_names(env, "res.partner", partner_ids)
        return sorted(
            ({"id": pid, "name": name} for pid, name in partner_names.items()),
            key=lambda p: p["name"],
        )

    @http.route("/checking_account_withdrawals/filters", type="json", auth="user")
    def filters(self, **kwargs):
        """Metadatos para poblar los selectores del dashboard."""
        self._check_access()
        env = request.env
        env.cr.execute("""
            SELECT MIN(date) AS min_date, MAX(date) AS max_date
            FROM caw_withdrawal WHERE company_id IN %s
        """, [tuple(env.companies.ids)])
        dates = env.cr.dictfetchone() or {}
        return {
            "companies": [
                {"id": c.id, "name": c.display_name} for c in env.companies
            ],
            "partners": self._caw_partners(env),
            "min_date": str(dates.get("min_date") or ""),
            "max_date": str(dates.get("max_date") or ""),
        }

    @http.route("/checking_account_withdrawals/metrics", type="json", auth="user")
    def metrics(self, start_date=None, end_date=None, company="all", partner="all", **kwargs):
        """KPIs y series de gráficos del dashboard."""
        self._check_access()
        env = request.env
        return {
            "kpis": self._caw_kpis(env, start_date, end_date, company, partner),
            "charts": self._caw_charts(env, start_date, end_date, company, partner),
        }

    def _caw_records_domain(self, env, model, start_date, end_date, company, partner, search):
        """Arma el dominio y resuelve el modelo/campo de fecha para retiros o cuotas.

        Compartido por `records()` (paginado, para la tabla del dashboard) y `export()`
        (sin cap de página, para el CSV) para que ambos filtren exactamente igual.
        """
        domain = [("company_id", "in", env.companies.ids)]
        if company and company != "all":
            domain.append(("company_id", "=", int(company)))
        if partner and partner != "all":
            domain.append(("partner_id", "=", int(partner)))
        if model == "installments":
            record_model = env["caw.installment"]
            date_field = "date_due"
        else:
            record_model = env["caw.withdrawal"]
            date_field = "date"
            domain.append(("state", "not in", ("draft", "cancel")))
        if start_date:
            domain.append((date_field, ">=", start_date))
        if end_date:
            domain.append((date_field, "<=", end_date))
        if search:
            domain.append(("partner_id", "ilike", search))
        return domain, record_model, date_field

    @http.route("/checking_account_withdrawals/records", type="json", auth="user")
    def records(self, model="withdrawals", start_date=None, end_date=None, company="all",
                partner="all", search=None, page=1, per_page=15, **kwargs):
        """Listado paginado de retiros o cuotas para las pestañas del dashboard."""
        self._check_access()
        env = request.env
        page = max(int(page or 1), 1)
        per_page = min(max(int(per_page or 15), 1), 200)
        domain, record_model, date_field = self._caw_records_domain(
            env, model, start_date, end_date, company, partner, search
        )
        total = record_model.search_count(domain)
        records = record_model.search(
            domain, offset=(page - 1) * per_page, limit=per_page, order=f"{date_field} desc"
        )
        return {
            "records": [self._caw_serialize(record, model) for record in records],
            "page": page,
            "pages": max((total + per_page - 1) // per_page, 1),
            "total": total,
        }

    def _caw_serialize(self, record, model):
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
        }

    @http.route("/checking_account_withdrawals/export", type="http", auth="user")
    def export(self, model="withdrawals", start_date=None, end_date=None, company="all",
               partner="all", search=None, **kwargs):
        """Exporta el listado filtrado a CSV, sin el cap de 200 filas que usa la tabla del
        dashboard (esa paginación es solo para la UI). El límite de 50000 es un resguardo
        de memoria, no un tope de negocio: en la práctica ninguna cartera lo alcanza."""
        self._check_access()
        env = request.env
        domain, record_model, date_field = self._caw_records_domain(
            env, model, start_date, end_date, company, partner, search
        )
        records = record_model.search(domain, limit=50000, order=f"{date_field} desc")
        rows = [self._caw_serialize(record, model) for record in records]
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), delimiter=";")
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
