# -*- coding: utf-8 -*-
import logging

from odoo import fields, http
from odoo.http import request
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class PriceChangeMetricsController(http.Controller):

    def _check_access(self):
        """Bloquea el acceso si el usuario no está en el grupo del módulo."""
        if not request.env.user.has_group(
            "product_price_change_metrics.group_price_change_metrics_user"
        ):
            raise AccessError("No tienes permisos para ver los cambios de precio.")

    def _window_domain(self, window):
        """Dominio por ventana temporal (días) sobre change_date; [] si 'all'."""
        if not window or window == "all":
            return []
        try:
            days = int(window)
        except (TypeError, ValueError):
            days = 30
        limit_date = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        return [("change_date", ">=", limit_date)]

    def _base_domain(self, company, window, category, search):
        """Construye el dominio común (sin filtro de estado)."""
        domain = self._window_domain(window)
        if company == "current":
            domain.append(("company_id", "=", request.env.company.id))
        elif company and company != "all":
            domain.append(("company_id", "=", int(company)))
        if category and category != "all":
            domain.append(("product_tmpl_id.categ_id", "=", int(category)))
        if search:
            domain.append(("product_tmpl_id.name", "ilike", search))
        return domain

    @http.route("/product_price_change_metrics/filters", type="json", auth="user")
    def get_filters(self, **kwargs):
        """Datos para poblar los filtros del dashboard."""
        self._check_access()
        companies = request.env.companies
        categories = request.env["product.category"].search([])
        return {
            "companies": [{"id": c.id, "name": c.name} for c in companies],
            "current_company": request.env.company.id,
            "categories": [{"id": c.id, "name": c.display_name} for c in categories],
        }

    @http.route("/product_price_change_metrics/changes", type="json", auth="user")
    def get_changes(self, company="current", state="pending", window="30",
                    category="all", search=None, page=1, per_page=20, **kwargs):
        """Lista paginada de cambios de precio filtrados + contador de pendientes."""
        self._check_access()
        base_domain = self._base_domain(company, window, category, search)
        domain = list(base_domain)
        if state and state != "all":
            domain.append(("state", "=", state))

        Log = request.env["product.price.log"]
        per_page = int(per_page or 20)
        page = max(1, int(page or 1))
        total = Log.search_count(domain)
        pages = max(1, (total + per_page - 1) // per_page)
        records = Log.search(
            domain, limit=per_page, offset=(page - 1) * per_page,
            order="change_date desc, id desc",
        )
        rows = []
        for r in records:
            rows.append({
                "id": r.id,
                "product_tmpl_id": r.product_tmpl_id.id,
                "product": r.product_tmpl_id.display_name,
                "category": r.product_tmpl_id.categ_id.display_name or "—",
                "source": "Global" if r.source == "global" else (r.pricelist_id.display_name or "Lista"),
                "old_price": round(r.old_price, 2),
                "new_price": round(r.new_price, 2),
                "diff_amount": round(r.diff_amount, 2),
                "date": fields.Datetime.to_string(r.change_date),
                "state": r.state,
                "done_by": r.done_user_id.name or "",
            })
        pending = Log.search_count(base_domain + [("state", "=", "pending")])
        return {"rows": rows, "page": page, "pages": pages, "total": total, "pending": pending}

    @http.route("/product_price_change_metrics/mark_done", type="json", auth="user")
    def mark_done(self, ids=None, done=True, **kwargs):
        """Marca filas como actualizadas/pendientes en góndola (solo de sus empresas)."""
        self._check_access()
        ids = [int(i) for i in (ids or [])]
        if not ids:
            return {"updated": 0}
        records = request.env["product.price.log"].search([
            ("id", "in", ids),
            ("company_id", "in", request.env.companies.ids),
        ])
        if done:
            vals = {
                "state": "done",
                "done_user_id": request.env.uid,
                "done_date": fields.Datetime.now(),
            }
        else:
            vals = {"state": "pending", "done_user_id": False, "done_date": False}
        records.sudo().write(vals)
        return {"updated": len(records)}
