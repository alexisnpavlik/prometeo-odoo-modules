# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
import datetime
import csv
import io
import logging

_logger = logging.getLogger(__name__)

INVOICE_STATES = {
    "draft": "Borrador",
    "posted": "Publicada",
    "cancel": "Cancelada",
}


class AccountMetricsController(http.Controller):

    def _check_access(self):
        """Valida que el usuario pertenezca al grupo de métricas de facturación."""
        if not request.env.user.has_group("account_management_metrics.group_account_metrics_user"):
            raise AccessError("No tienes permisos para acceder a las métricas de facturación.")

    def _get_timezone(self):
        return request.env.user.tz or "America/Argentina/Buenos_Aires"

    def _resolve_names(self, model, ids):
        """Resuelve {id: display_name} vía ORM con sudo (solo lectura de etiquetas).

        Evita depender del tipo de columna (jsonb traducible o varchar) en SQL crudo
        y respeta la traducción del usuario.
        """
        ids = [i for i in set(ids) if i]
        if not ids:
            return {}
        records = request.env[model].sudo().browse(ids)
        return {rec.id: rec.display_name for rec in records}

    def _build_where_clause(self, start_date=None, end_date=None, company="all", journal="all",
                            doc_type="all", salesperson="all", search=None, state="all"):
        """Construye el WHERE parametrizado sobre account_move (alias am).

        El filtro search solo debe usarse en queries que joinean res_partner (rp)
        y el partner del vendedor (rup).
        """
        allowed_companies = tuple(request.env.companies.ids)
        where_clause = "am.move_type IN ('out_invoice', 'out_refund') AND am.company_id IN %s"
        params = [allowed_companies]

        if start_date:
            where_clause += " AND COALESCE(am.invoice_date, am.date) >= %s"
            params.append(start_date)
        if end_date:
            where_clause += " AND COALESCE(am.invoice_date, am.date) <= %s"
            params.append(end_date)

        if company and company != "all":
            where_clause += " AND am.company_id = %s"
            params.append(int(company))
        if journal and journal != "all":
            where_clause += " AND am.journal_id = %s"
            params.append(int(journal))
        if doc_type and doc_type != "all":
            where_clause += " AND am.l10n_latam_document_type_id = %s"
            params.append(int(doc_type))
        if salesperson and salesperson != "all":
            where_clause += " AND am.invoice_user_id = %s"
            params.append(int(salesperson))
        if state and state != "all" and state in INVOICE_STATES:
            where_clause += " AND am.state = %s"
            params.append(state)

        if search:
            search_pattern = f"%{search.lower()}%"
            where_clause += """ AND (
                LOWER(am.name) LIKE %s OR
                LOWER(COALESCE(rp.name, '')) LIKE %s OR
                LOWER(COALESCE(rup.name, '')) LIKE %s
            )"""
            params.extend([search_pattern, search_pattern, search_pattern])

        return where_clause, params

    @http.route("/account_management_metrics/filters", type="json", auth="user")
    def get_filters(self, **kwargs):
        """Devuelve las opciones de filtrado disponibles según los comprobantes existentes."""
        self._check_access()
        cr = request.env.cr
        allowed_companies = tuple(request.env.companies.ids)

        # 1. Empresas permitidas
        companies = [{"id": c.id, "name": c.name} for c in request.env.companies]

        # 2. Tipos de documento usados (Factura A/B/C, NC, ND...)
        cr.execute("""
            SELECT DISTINCT am.l10n_latam_document_type_id
            FROM account_move am
            WHERE am.move_type IN ('out_invoice', 'out_refund')
              AND am.company_id IN %s
              AND am.l10n_latam_document_type_id IS NOT NULL
        """, (allowed_companies,))
        doc_type_ids = [r[0] for r in cr.fetchall()]
        doc_type_names = self._resolve_names("l10n_latam.document.type", doc_type_ids)
        doc_types = sorted(
            [{"id": did, "name": name} for did, name in doc_type_names.items()],
            key=lambda d: d["name"],
        )

        # 3. Rango de fechas min/max
        cr.execute("""
            SELECT MIN(COALESCE(am.invoice_date, am.date)),
                   MAX(COALESCE(am.invoice_date, am.date))
            FROM account_move am
            WHERE am.move_type IN ('out_invoice', 'out_refund')
              AND am.company_id IN %s
        """, (allowed_companies,))
        row = cr.fetchone()
        min_date = row[0].strftime("%Y-%m-%d") if row and row[0] else None
        max_date = row[1].strftime("%Y-%m-%d") if row and row[1] else None

        return {
            "companies": companies,
            "doc_types": doc_types,
            "min_date": min_date,
            "max_date": max_date,
        }

    def _get_payment_methods(self, posted_move_ids):
        """Cobros por medio de pago sobre los comprobantes del período.

        - Facturas emitidas desde el POS: se toman sus pagos reales de pos_payment
          (Efectivo, Tarjeta, Mercadopago...) agrupados por método de pago del POS.
        - Resto de comprobantes: montos conciliados (account_partial_reconcile)
          agrupados por el diario del asiento contraparte (Banco, Efectivo...).
          Las facturas suman y las notas de crédito restan; se excluyen las
          conciliaciones entre comprobantes del mismo conjunto (NC aplicada a
          factura) para no contar una NC como medio de pago.
        """
        cr = request.env.cr
        if not posted_move_ids:
            return {"labels": [], "values": []}

        totals = {}  # label -> monto
        pos_move_ids = set()

        # 1. Facturas originadas en POS: medio de pago real del ticket
        if "pos.payment" in request.env:
            cr.execute("""
                SELECT po.account_move, pay.payment_method_id, SUM(pay.amount) AS monto
                FROM pos_payment pay
                JOIN pos_order po ON po.id = pay.pos_order_id
                WHERE po.account_move IN %s
                GROUP BY po.account_move, pay.payment_method_id
            """, (tuple(posted_move_ids),))
            pos_rows = cr.fetchall()
            pos_move_ids = {r[0] for r in pos_rows}
            method_names = self._resolve_names("pos.payment.method", [r[1] for r in pos_rows])
            for _move_id, method_id, monto in pos_rows:
                label = method_names.get(method_id, "Desconocido")
                totals[label] = totals.get(label, 0.0) + float(monto or 0.0)

        # 2. Resto de comprobantes: conciliaciones contra el diario contraparte
        other_ids = tuple(set(posted_move_ids) - pos_move_ids)
        if other_ids:
            all_ids = tuple(posted_move_ids)
            journal_totals = {}
            # Facturas: línea receivable al debe, contraparte (pago) al haber
            cr.execute("""
                SELECT pm.journal_id, SUM(apr.amount) AS monto
                FROM account_partial_reconcile apr
                JOIN account_move_line li ON li.id = apr.debit_move_id
                JOIN account_move_line lp ON lp.id = apr.credit_move_id
                JOIN account_move pm ON pm.id = lp.move_id
                WHERE li.move_id IN %s AND lp.move_id NOT IN %s
                GROUP BY pm.journal_id
            """, (other_ids, all_ids))
            for journal_id, monto in cr.fetchall():
                journal_totals[journal_id] = journal_totals.get(journal_id, 0.0) + float(monto or 0.0)

            # Notas de crédito: línea receivable al haber, contraparte al debe (restan)
            cr.execute("""
                SELECT pm.journal_id, SUM(apr.amount) AS monto
                FROM account_partial_reconcile apr
                JOIN account_move_line li ON li.id = apr.credit_move_id
                JOIN account_move_line lp ON lp.id = apr.debit_move_id
                JOIN account_move pm ON pm.id = lp.move_id
                WHERE li.move_id IN %s AND lp.move_id NOT IN %s
                GROUP BY pm.journal_id
            """, (other_ids, all_ids))
            for journal_id, monto in cr.fetchall():
                journal_totals[journal_id] = journal_totals.get(journal_id, 0.0) - float(monto or 0.0)

            journal_names = self._resolve_names("account.journal", list(journal_totals.keys()))
            for journal_id, monto in journal_totals.items():
                label = journal_names.get(journal_id, "Desconocido")
                totals[label] = totals.get(label, 0.0) + monto

        rows = sorted(
            [(label, round(monto, 2)) for label, monto in totals.items()],
            key=lambda r: r[1], reverse=True,
        )
        return {
            "labels": [r[0] for r in rows],
            "values": [r[1] for r in rows],
        }

    @http.route("/account_management_metrics/metrics", type="json", auth="user")
    def get_metrics(self, start_date=None, end_date=None, company="all", journal="all",
                    doc_type="all", salesperson="all", **kwargs):
        """KPIs y gráficos de facturación para el período y filtros indicados."""
        self._check_access()
        cr = request.env.cr

        where_clause, params = self._build_where_clause(
            start_date, end_date, company, journal, doc_type, salesperson)

        # 1. KPIs en una sola pasada con FILTER
        cr.execute(f"""
            SELECT
                COALESCE(SUM(am.amount_total_signed)   FILTER (WHERE am.state = 'posted'), 0) AS total_facturado,
                COALESCE(SUM(am.amount_untaxed_signed) FILTER (WHERE am.state = 'posted'), 0) AS total_facturado_neto,
                COUNT(*) FILTER (WHERE am.state = 'posted')                                   AS comprobantes_emitidos,
                COUNT(*) FILTER (WHERE am.state = 'posted' AND am.move_type = 'out_invoice')  AS facturas_emitidas,
                COUNT(*) FILTER (WHERE am.state = 'posted' AND am.move_type = 'out_refund')   AS nc_emitidas,
                COALESCE(SUM(am.amount_total) FILTER (WHERE am.state = 'posted' AND am.move_type = 'out_refund'), 0) AS monto_nc,
                COUNT(*) FILTER (WHERE am.state = 'draft')                                    AS borradores,
                COALESCE(SUM(am.amount_total) FILTER (WHERE am.state = 'draft'), 0)           AS monto_borradores,
                COUNT(*) FILTER (WHERE am.state = 'cancel')                                   AS canceladas,
                COALESCE(SUM(am.amount_total) FILTER (WHERE am.state = 'cancel'), 0)          AS monto_canceladas
            FROM account_move am
            WHERE {where_clause}
        """, params)
        k = cr.dictfetchone() or {}

        facturas_emitidas = int(k.get("facturas_emitidas") or 0)
        comprobantes_emitidos = int(k.get("comprobantes_emitidos") or 0)
        canceladas = int(k.get("canceladas") or 0)
        total_facturado = float(k.get("total_facturado") or 0.0)
        emitidos_mas_canceladas = comprobantes_emitidos + canceladas

        kpis = {
            "total_facturado": round(total_facturado, 2),
            "total_facturado_neto": round(float(k.get("total_facturado_neto") or 0.0), 2),
            "comprobantes_emitidos": comprobantes_emitidos,
            "facturas_emitidas": facturas_emitidas,
            "promedio_por_factura": round(total_facturado / facturas_emitidas, 2) if facturas_emitidas else 0.0,
            "nc_emitidas": int(k.get("nc_emitidas") or 0),
            "monto_nc": round(float(k.get("monto_nc") or 0.0), 2),
            "borradores": int(k.get("borradores") or 0),
            "monto_borradores": round(float(k.get("monto_borradores") or 0.0), 2),
            "canceladas": canceladas,
            "monto_canceladas": round(float(k.get("monto_canceladas") or 0.0), 2),
            "tasa_cancelacion": round(canceladas / emitidos_mas_canceladas * 100.0, 2) if emitidos_mas_canceladas else 0.0,
        }

        # 2. Tendencia diaria de facturación por empresa (solo publicados)
        cr.execute(f"""
            SELECT COALESCE(am.invoice_date, am.date) AS fecha,
                   am.company_id,
                   SUM(am.amount_total_signed) AS subtotal
            FROM account_move am
            WHERE {where_clause} AND am.state = 'posted'
            GROUP BY fecha, am.company_id
            ORDER BY fecha
        """, params)
        trend_rows = cr.fetchall()
        unique_dates = sorted(set(r[0] for r in trend_rows if r[0]))
        company_names = self._resolve_names("res.company", [r[1] for r in trend_rows])
        subtotal_map = {(r[0], r[1]): round(float(r[2] or 0.0), 2) for r in trend_rows}
        companies_data = {}
        for cid, cname in sorted(company_names.items(), key=lambda i: i[1]):
            companies_data[cname] = [subtotal_map.get((d, cid), 0.0) for d in unique_dates]
        invoicing_trend = {
            "labels": [d.strftime("%d/%m/%Y") for d in unique_dates],
            "companies": companies_data,
            "timeframe": "Diario",
        }

        # 3. Ventas totales (POS) vs facturado con ARCA, por día
        # Detecta la venta no respaldada por comprobante fiscal: compara el total
        # vendido en el POS contra la facturación publicada (neta de NC).
        inv_by_date = {}
        for fecha, _cid, subtotal in trend_rows:
            if fecha:
                inv_by_date[fecha] = inv_by_date.get(fecha, 0.0) + float(subtotal or 0.0)

        pos_by_date = {}
        if "pos.order" in request.env:
            tz = self._get_timezone()
            pos_where = "po.state IN ('paid', 'done', 'invoiced') AND po.company_id IN %s"
            pos_params = [tz, tuple(request.env.companies.ids)]
            if company and company != "all":
                pos_where += " AND po.company_id = %s"
                pos_params.append(int(company))
            if start_date:
                pos_where += " AND po.date_order >= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
                pos_params.extend([f"{start_date} 00:00:00", tz])
            if end_date:
                pos_where += " AND po.date_order <= (%s::timestamp AT TIME ZONE %s AT TIME ZONE 'UTC')"
                pos_params.extend([f"{end_date} 23:59:59", tz])
            cr.execute(f"""
                SELECT (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS fecha,
                       SUM(po.amount_total) AS total
                FROM pos_order po
                WHERE {pos_where}
                GROUP BY fecha
            """, pos_params)
            pos_by_date = {r[0]: float(r[1] or 0.0) for r in cr.fetchall() if r[0]}

        vs_dates = sorted(set(inv_by_date) | set(pos_by_date))
        total_ventas = round(sum(pos_by_date.values()), 2)
        total_facturado_vs = round(sum(inv_by_date.values()), 2)
        sales_vs_invoiced = {
            "labels": [d.strftime("%d/%m/%Y") for d in vs_dates],
            "ventas": [round(pos_by_date.get(d, 0.0), 2) for d in vs_dates],
            "facturado": [round(inv_by_date.get(d, 0.0), 2) for d in vs_dates],
            "total_ventas": total_ventas,
            "total_facturado": total_facturado_vs,
            "diferencia": round(total_ventas - total_facturado_vs, 2),
        }

        # 4. Facturación por empresa
        cr.execute(f"""
            SELECT am.company_id, SUM(am.amount_total_signed) AS subtotal
            FROM account_move am
            WHERE {where_clause} AND am.state = 'posted'
            GROUP BY am.company_id
            ORDER BY subtotal DESC
        """, params)
        company_rows = cr.fetchall()
        company_names = self._resolve_names("res.company", [r[0] for r in company_rows])
        by_company = {
            "labels": [company_names.get(r[0], "Desconocido") for r in company_rows],
            "values": [round(float(r[1] or 0.0), 2) for r in company_rows],
        }

        # 5. Comprobantes emitidos por tipo (Factura A/B/C, NC, ND...)
        cr.execute(f"""
            SELECT am.l10n_latam_document_type_id,
                   COUNT(*) AS cantidad,
                   SUM(am.amount_total_signed) AS monto
            FROM account_move am
            WHERE {where_clause} AND am.state = 'posted'
            GROUP BY am.l10n_latam_document_type_id
            ORDER BY cantidad DESC
        """, params)
        doc_rows = cr.fetchall()
        doc_names = self._resolve_names("l10n_latam.document.type", [r[0] for r in doc_rows])
        doc_types_chart = {
            "labels": [doc_names.get(r[0], "Sin tipo de documento") for r in doc_rows],
            "counts": [int(r[1]) for r in doc_rows],
            "amounts": [round(float(r[2] or 0.0), 2) for r in doc_rows],
        }

        # 6. Distribución por estado (doughnut)
        cr.execute(f"""
            SELECT am.state, COUNT(*)
            FROM account_move am
            WHERE {where_clause}
            GROUP BY am.state
        """, params)
        state_data = {r[0]: int(r[1]) for r in cr.fetchall()}
        status_chart = {
            "labels": [INVOICE_STATES[s] for s in ("posted", "draft", "cancel")],
            "values": [state_data.get(s, 0) for s in ("posted", "draft", "cancel")],
        }

        # 7. Cobros por medio de pago (sobre los comprobantes publicados filtrados)
        cr.execute(f"""
            SELECT am.id FROM account_move am
            WHERE {where_clause} AND am.state = 'posted'
        """, params)
        posted_ids = [r[0] for r in cr.fetchall()]
        payment_methods = self._get_payment_methods(posted_ids)

        return {
            "kpis": kpis,
            "charts": {
                "invoicing_trend": invoicing_trend,
                "sales_vs_invoiced": sales_vs_invoiced,
                "by_company": by_company,
                "doc_types": doc_types_chart,
                "status": status_chart,
                "payment_methods": payment_methods,
            },
        }

    def _query_raw_invoices(self, where_clause, params, limit=None, offset=None):
        """Consulta el detalle de comprobantes con joins de cliente y vendedor."""
        cr = request.env.cr
        query = f"""
            SELECT
                am.id                                AS move_id,
                am.name                              AS numero,
                COALESCE(am.invoice_date, am.date)   AS fecha,
                am.l10n_latam_document_type_id       AS doc_type_id,
                am.journal_id                        AS journal_id,
                am.company_id                        AS company_id,
                am.invoice_user_id                   AS user_id,
                rp.name                              AS cliente,
                am.state                             AS estado,
                am.move_type                         AS move_type,
                am.amount_total                      AS total,
                am.amount_residual                   AS saldo
            FROM account_move am
            LEFT JOIN res_partner rp ON rp.id = am.partner_id
            LEFT JOIN res_users ru ON ru.id = am.invoice_user_id
            LEFT JOIN res_partner rup ON rup.id = ru.partner_id
            WHERE {where_clause}
            ORDER BY COALESCE(am.invoice_date, am.date) DESC, am.id DESC
        """
        query_params = list(params)
        if limit is not None:
            query += " LIMIT %s OFFSET %s"
            query_params.extend([limit, offset or 0])
        cr.execute(query, query_params)
        rows = cr.dictfetchall()

        doc_names = self._resolve_names("l10n_latam.document.type", [r["doc_type_id"] for r in rows])
        journal_names = self._resolve_names("account.journal", [r["journal_id"] for r in rows])
        company_names = self._resolve_names("res.company", [r["company_id"] for r in rows])
        user_names = self._resolve_names("res.users", [r["user_id"] for r in rows])

        for r in rows:
            sign = -1.0 if r["move_type"] == "out_refund" else 1.0
            r["fecha"] = r["fecha"].strftime("%d/%m/%Y") if r["fecha"] else ""
            r["tipo_doc"] = doc_names.get(r["doc_type_id"], "Sin tipo")
            r["diario"] = journal_names.get(r["journal_id"], "")
            r["empresa"] = company_names.get(r["company_id"], "")
            r["vendedor"] = user_names.get(r["user_id"], "")
            r["cliente"] = r["cliente"] or "Consumidor Final"
            r["estado_label"] = INVOICE_STATES.get(r["estado"], r["estado"])
            r["total"] = round(sign * float(r["total"] or 0.0), 2)
            r["saldo"] = round(sign * float(r["saldo"] or 0.0), 2)
            for key in ("doc_type_id", "journal_id", "company_id", "user_id", "move_type"):
                r.pop(key, None)
        return rows

    @http.route("/account_management_metrics/raw_invoices", type="json", auth="user")
    def get_raw_invoices(self, start_date=None, end_date=None, company="all", journal="all",
                         doc_type="all", salesperson="all", search=None, state="all",
                         page=1, per_page=15, **kwargs):
        """Detalle paginado de comprobantes con búsqueda difusa y filtro opcional de estado."""
        self._check_access()
        cr = request.env.cr

        where_clause, params = self._build_where_clause(
            start_date, end_date, company, journal, doc_type, salesperson, search, state)

        cr.execute(f"""
            SELECT COUNT(*)
            FROM account_move am
            LEFT JOIN res_partner rp ON rp.id = am.partner_id
            LEFT JOIN res_users ru ON ru.id = am.invoice_user_id
            LEFT JOIN res_partner rup ON rup.id = ru.partner_id
            WHERE {where_clause}
        """, params)
        total_rows = cr.fetchone()[0] or 0
        total_pages = max(1, (total_rows + per_page - 1) // per_page)
        offset = (page - 1) * per_page

        invoices = self._query_raw_invoices(where_clause, params, limit=per_page, offset=offset)

        return {
            "invoices": invoices,
            "page": page,
            "pages": total_pages,
            "total": total_rows,
        }

    @http.route("/account_management_metrics/export", type="http", auth="user")
    def export_csv(self, start_date=None, end_date=None, company="all", journal="all",
                   doc_type="all", salesperson="all", search=None, **kwargs):
        """Exporta el detalle de comprobantes filtrado a CSV (con BOM para Excel)."""
        try:
            self._check_access()

            # Sanitizar filtros en caso de peticiones http GET planas
            start_date = start_date if start_date and start_date not in ("null", "") else None
            end_date = end_date if end_date and end_date not in ("null", "") else None
            company = company or "all"
            journal = journal or "all"
            doc_type = doc_type or "all"
            salesperson = salesperson or "all"
            search = search if search and search != "null" else None

            where_clause, params = self._build_where_clause(
                start_date, end_date, company, journal, doc_type, salesperson, search)
            rows = self._query_raw_invoices(where_clause, params)

            output = io.StringIO()
            output.write("\ufeff")  # BOM para soporte Excel nativo con acentos
            writer = csv.writer(output, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow([
                "Número", "Fecha", "Tipo de Comprobante", "Cliente", "Empresa",
                "Diario (Sucursal)", "Vendedor", "Estado", "Total", "Saldo Pendiente",
            ])
            for r in rows:
                writer.writerow([
                    r["numero"], r["fecha"], r["tipo_doc"], r["cliente"], r["empresa"],
                    r["diario"], r["vendedor"], r["estado_label"], r["total"], r["saldo"],
                ])

            csv_data = output.getvalue()
            output.close()

            filename = f"reporte_facturacion_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            return request.make_response(
                csv_data,
                headers=[
                    ("Content-Type", "text/csv; charset=utf-8"),
                    ("Content-Disposition", f'attachment; filename="{filename}"'),
                ],
            )
        except Exception as e:
            _logger.exception("Error exportando reporte de facturación")
            return request.make_response(str(e), status=500)
