# -*- coding: utf-8 -*-
import io
import json
import logging
from collections import defaultdict
from datetime import datetime

import xlsxwriter

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)

MANAGER_GROUP = "stock_branch_transfer.group_branch_transfer_manager"
PERIODS = (7, 30, 90, 180, 365)
DEFAULT_PERIOD = 30
# Traslados abiertos: aparecen siempre, aunque se hayan creado antes del período
OPEN_STATES = ("draft", "in_transit", "with_diff")
RECEIVED_STATES = ("received", "with_diff", "closed")
# Días en camino a partir de los cuales un traslado se marca demorado
LATE_DAYS = 3
UNCATEGORIZED = "Sin categorizar"
STATUS_LABELS = {
    "draft": "Borrador",
    "in_transit": "En camino",
    "with_diff": "Con diferencias",
    "received": "Recibido",
    "closed": "Cerrado",
}


def _to_list(value):
    """Filtro multi-selección: lista, JSON de lista o valor suelto. Vacío o 'all' = sin filtro."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, str):
        value = [value]
    return [v for v in (value or []) if v and v != "all"]


def _to_int(value, allowed, default):
    """Entero validado contra una lista blanca; cualquier otra cosa cae al default."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value in allowed else default


def _fmt_date(value):
    """Fecha para mostrar; datetime no es serializable a JSON."""
    return value.strftime("%d/%m/%Y") if value else None


class BranchTransferMetricsController(http.Controller):

    def _check_access(self):
        """Las métricas muestran costos: sólo managers de Traslados."""
        if not request.env.user.has_group(MANAGER_GROUP):
            raise AccessError("Sólo los managers de Traslados pueden ver las métricas.")

    def _fetch_lines(self, period):
        """Líneas de traslados no anulados: abiertos siempre, el resto si se enviaron (o crearon) en el período.

        Costo = costo actual del producto en la sucursal de origen (mismo dato que la columna Costo).
        """
        cr = request.env.cr
        cr.execute("""
            SELECT t.id AS transfer_id, t.name, t.state,
                   t.company_id, t.dest_company_id,
                   co.name AS origen, cd.name AS destino,
                   COALESCE(t.date_sent, t.create_date) AS fecha,
                   t.date_sent, t.date_received,
                   l.product_id,
                   COALESCE(pt.name->>%(lang)s, pt.name->>'en_US') AS producto,
                   pp.barcode,
                   pc.complete_name AS categoria,
                   COALESCE(l.qty_sent, 0) AS qty_sent,
                   COALESCE(l.qty_received, 0) AS qty_received,
                   COALESCE((pp.standard_price->>(t.company_id::text))::numeric, 0) AS unit_cost
            FROM stock_branch_transfer t
            JOIN stock_branch_transfer_line l ON l.transfer_id = t.id
            JOIN res_company co ON co.id = t.company_id
            JOIN res_company cd ON cd.id = t.dest_company_id
            JOIN product_product pp ON pp.id = l.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            WHERE t.state <> 'cancel'
              AND (t.state IN %(open)s
                   OR COALESCE(t.date_sent, t.create_date) >= NOW() - %(period)s * INTERVAL '1 day')
            ORDER BY fecha DESC, t.id DESC, l.id
        """, {"lang": request.env.context.get("lang") or "es_AR", "open": OPEN_STATES, "period": period})
        return cr.dictfetchall()

    def _build_lines(self, period):
        """Líneas planas con montos, diferencia y ruta, listas para agrupar."""
        Line = request.env["stock.branch.transfer.line"]
        Product = request.env["product.product"].sudo()
        Company = request.env["res.company"].sudo()
        rows = self._fetch_lines(period)
        # Precio de venta en lote por empresa destino: de a uno tardaba ~10 s
        by_company = defaultdict(set)
        for r in rows:
            by_company[r["dest_company_id"]].add(r["product_id"])
        prices = {}
        for company_id, product_ids in by_company.items():
            company_prices = Line._sale_prices_for(Product.browse(list(product_ids)), Company.browse(company_id))
            prices.update({(pid, company_id): price for pid, (price, _source) in company_prices.items()})
        now = datetime.now()
        lines = []
        for r in rows:
            key = (r["product_id"], r["dest_company_id"])
            sent = float(r["qty_sent"])
            received = float(r["qty_received"])
            unit_cost = float(r["unit_cost"])
            # Diferencia sólo cuando ya se recibió: en camino, "recibido 0" no es faltante
            diff = received - sent if r["state"] in RECEIVED_STATES else 0.0
            hours = None
            if r["date_sent"] and r["date_received"]:
                hours = (r["date_received"] - r["date_sent"]).total_seconds() / 3600
            lines.append({
                "transfer_id": r["transfer_id"],
                "name": r["name"],
                "status": r["state"],
                "origen": r["origen"],
                "destino": r["destino"],
                "route": f"{r['origen']} → {r['destino']}",
                "fecha": r["fecha"],
                "date_sent": r["date_sent"],
                "days": (now - r["date_sent"]).days if r["state"] == "in_transit" and r["date_sent"] else None,
                "hours": hours,
                "product_id": r["product_id"],
                "producto": r["producto"] or "",
                "barcode": r["barcode"],
                "categoria": r["categoria"] or UNCATEGORIZED,
                "sent": sent,
                "received": received,
                "diff": diff,
                "cost": sent * unit_cost,
                "sale": sent * prices[key],
                # + 0.0: un faltante de producto sin costo da -0.0 y el Excel muestra "-0"
                "diff_cost": diff * unit_cost + 0.0,
            })
        return lines

    def _compute(self, company, period, status, route, category, barcode):
        """Todo el dashboard con los filtros aplicados. Lo usan la pantalla y el Excel."""
        company, status = _to_list(company), _to_list(status)
        route, category, barcode = _to_list(route), _to_list(category), _to_list(barcode)

        base = [ln for ln in self._build_lines(period)
                if not company or ln["origen"] in company or ln["destino"] in company]
        options = {
            "routes": sorted({ln["route"] for ln in base}),
            "categories": sorted({ln["categoria"] for ln in base}),
        }
        # Sin el filtro de estado: las tarjetas no se vacían al elegir una
        unfiltered = [ln for ln in base
                      if (not route or ln["route"] in route)
                      and (not category or ln["categoria"] in category)
                      and (not barcode or ln["barcode"] in barcode)]
        rows = [ln for ln in unfiltered if not status or ln["status"] in status]
        # Plata enviada: los borradores no salieron, salvo que se pidan explícitamente
        moved = [ln for ln in rows if ln["status"] != "draft" or "draft" in status]

        return {
            "cards": self._cards(unfiltered),
            "totals": self._totals(moved),
            "options": options,
            "pending": self._pending(rows),
            "routes": self._routes(moved),
            "diffs": self._diffs(rows),
            "products": self._products(moved),
        }

    def _cards(self, lines):
        """Cantidad de traslados y valor a costo por estado."""
        transfers, cost = defaultdict(set), defaultdict(float)
        for ln in lines:
            transfers[ln["status"]].add(ln["transfer_id"])
            cost[ln["status"]] += ln["cost"]
        return [{"key": key, "label": label, "count": len(transfers[key]), "cost": round(cost[key], 2)}
                for key, label in STATUS_LABELS.items()]

    def _transfer_hours(self, lines):
        """Horas de envío a recepción, una vez por traslado (no por línea)."""
        return {ln["transfer_id"]: ln["hours"] for ln in lines if ln["hours"] is not None}

    def _totals(self, lines):
        """Resumen de lo movido en el período."""
        hours = list(self._transfer_hours(lines).values())
        return {
            "transfers": len({ln["transfer_id"] for ln in lines}),
            "units": round(sum(ln["sent"] for ln in lines), 2),
            "cost": round(sum(ln["cost"] for ln in lines), 2),
            "sale": round(sum(ln["sale"] for ln in lines), 2),
            "missing_cost": round(abs(sum(ln["diff_cost"] for ln in lines if ln["diff"] < 0)), 2),
            "extra_cost": round(sum(ln["diff_cost"] for ln in lines if ln["diff"] > 0), 2),
            "avg_hours": round(sum(hours) / len(hours), 1) if hours else None,
        }

    def _pending(self, lines):
        """Traslados abiertos, uno por fila, del más viejo al más nuevo."""
        grouped = {}
        for ln in lines:
            if ln["status"] not in OPEN_STATES:
                continue
            t = grouped.setdefault(ln["transfer_id"], {
                "transfer_id": ln["transfer_id"], "name": ln["name"], "status": ln["status"],
                "origen": ln["origen"], "destino": ln["destino"], "fecha": _fmt_date(ln["fecha"]),
                "fecha_sort": ln["fecha"].isoformat(), "days": ln["days"],
                "late": ln["days"] is not None and ln["days"] >= LATE_DAYS,
                "units": 0.0, "cost": 0.0, "sale": 0.0,
            })
            t["units"] += ln["sent"]
            t["cost"] += ln["cost"]
            t["sale"] += ln["sale"]
        rows = sorted(grouped.values(), key=lambda t: t["fecha_sort"])
        for t in rows:
            for k in ("units", "cost", "sale"):
                t[k] = round(t[k], 2)
        return rows

    def _routes(self, lines):
        """Origen → destino: volumen, plata, diferencias y demora."""
        grouped = {}
        hours = self._transfer_hours(lines)
        for ln in lines:
            g = grouped.setdefault(ln["route"], {
                "route": ln["route"], "origen": ln["origen"], "destino": ln["destino"],
                "ids": set(), "units": 0.0, "cost": 0.0, "sale": 0.0, "diff": 0.0, "diff_cost": 0.0,
            })
            g["ids"].add(ln["transfer_id"])
            g["units"] += ln["sent"]
            g["cost"] += ln["cost"]
            g["sale"] += ln["sale"]
            g["diff"] += ln["diff"]
            g["diff_cost"] += ln["diff_cost"]
        rows = []
        for g in grouped.values():
            route_hours = [hours[t] for t in g["ids"] if t in hours]
            rows.append({
                "route": g["route"], "origen": g["origen"], "destino": g["destino"],
                "transfers": len(g["ids"]),
                "units": round(g["units"], 2), "cost": round(g["cost"], 2), "sale": round(g["sale"], 2),
                "diff": round(g["diff"], 2), "diff_cost": round(g["diff_cost"], 2),
                "avg_hours": round(sum(route_hours) / len(route_hours), 1) if route_hours else None,
                "max_hours": round(max(route_hours), 1) if route_hours else None,
            })
        return sorted(rows, key=lambda r: r["cost"], reverse=True)

    def _diffs(self, lines):
        """Una fila por línea recibida con faltante o sobrante, la mayor plata primero."""
        rows = [{
            "key": f"{ln['transfer_id']}-{idx}",
            "transfer_id": ln["transfer_id"], "name": ln["name"], "status": ln["status"],
            "fecha": _fmt_date(ln["fecha"]), "fecha_sort": ln["fecha"].isoformat(),
            "route": ln["route"], "producto": ln["producto"], "categoria": ln["categoria"],
            "sent": round(ln["sent"], 2), "received": round(ln["received"], 2),
            "diff": round(ln["diff"], 2), "diff_cost": round(ln["diff_cost"], 2),
        } for idx, ln in enumerate(lines) if abs(ln["diff"]) > 1e-6]
        return sorted(rows, key=lambda r: abs(r["diff_cost"]), reverse=True)

    def _products(self, lines):
        """Productos más trasladados: unidades, plata y diferencias."""
        grouped = {}
        for ln in lines:
            g = grouped.setdefault(ln["product_id"], {
                "product_id": ln["product_id"], "producto": ln["producto"], "categoria": ln["categoria"],
                "ids": set(), "routes": set(), "units": 0.0, "cost": 0.0, "sale": 0.0, "diff": 0.0,
            })
            g["ids"].add(ln["transfer_id"])
            g["routes"].add(ln["route"])
            g["units"] += ln["sent"]
            g["cost"] += ln["cost"]
            g["sale"] += ln["sale"]
            g["diff"] += ln["diff"]
        rows = [{
            "product_id": g["product_id"], "producto": g["producto"], "categoria": g["categoria"],
            "transfers": len(g["ids"]), "routes": len(g["routes"]),
            "units": round(g["units"], 2), "cost": round(g["cost"], 2),
            "sale": round(g["sale"], 2), "diff": round(g["diff"], 2),
        } for g in grouped.values()]
        return sorted(rows, key=lambda r: r["units"], reverse=True)

    @http.route("/stock_branch_transfer/metrics/filters", type="json", auth="user")
    def get_filters(self, **kwargs):
        """Empresas que participan en algún traslado (origen o destino)."""
        self._check_access()
        request.env.cr.execute("""
            SELECT DISTINCT c.name FROM res_company c
            JOIN stock_branch_transfer t ON c.id IN (t.company_id, t.dest_company_id)
            ORDER BY c.name
        """)
        return {"companies": [r[0] for r in request.env.cr.fetchall()]}

    @http.route('/stock_branch_transfer/metrics/barcode_names', type='json', auth='user')
    def get_barcode_names(self, barcodes=None, **kwargs):
        """Nombre del producto de cada código de barras, para confirmar en el filtro lo escaneado."""
        self._check_access()
        codes = _to_list(barcodes)
        if not codes:
            return {}
        request.env.cr.execute("""
            SELECT pp.barcode, COALESCE(pt.name->>%s, pt.name->>'en_US')
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE pp.barcode IN %s
        """, (request.env.context.get("lang") or "es_AR", tuple(codes)))
        return dict(request.env.cr.fetchall())

    @http.route('/stock_branch_transfer/metrics/barcode_search', type='json', auth='user')
    def search_barcodes(self, term='', **kwargs):
        """Productos con código de barras que contienen el texto en el código o en el nombre.

        Primero los que empiezan con lo escrito: es lo normal al tipear las primeras cifras del código.
        """
        self._check_access()
        term = (term or '').strip()
        if len(term) < 2:
            return []
        lang = request.env.context.get("lang") or "es_AR"
        escaped = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        request.env.cr.execute("""
            SELECT pp.barcode, COALESCE(pt.name->>%(lang)s, pt.name->>'en_US') AS name
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE pp.active AND pt.active
              AND COALESCE(pp.barcode, '') <> ''
              AND (pt.company_id IS NULL OR pt.company_id IN %(companies)s)
              AND (pp.barcode ILIKE %(like)s
                   OR COALESCE(pt.name->>%(lang)s, pt.name->>'en_US') ILIKE %(like)s)
            ORDER BY pp.barcode ILIKE %(prefix)s DESC, 2, 1
            LIMIT 15
        """, {
            'lang': lang,
            'companies': tuple(request.env.companies.ids),
            'like': f'%{escaped}%',
            'prefix': f'{escaped}%',
        })
        return request.env.cr.dictfetchall()

    @http.route("/stock_branch_transfer/metrics/data", type="json", auth="user")
    def get_data(self, company="all", period=None, status="all", route="all",
                 category="all", barcode="all", **kwargs):
        """Tarjetas, totales y tablas con los filtros aplicados."""
        self._check_access()
        period = _to_int(period, PERIODS, DEFAULT_PERIOD)
        return self._compute(company, period, status, route, category, barcode)

    @http.route("/stock_branch_transfer/metrics/export", type="http", auth="user")
    def export_xlsx(self, company="all", period=None, status="all", route="all",
                    category="all", barcode="all", **kwargs):
        """Excel con una hoja por pestaña, mismos filtros que la pantalla."""
        try:
            self._check_access()
            period = _to_int(period, PERIODS, DEFAULT_PERIOD)
            data = self._compute(company, period, status, route, category, barcode)
            xlsx_data = self._render_xlsx(data, company, period)
            filename = f"metricas_traslados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            return request.make_response(xlsx_data, headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", f'attachment; filename="{filename}"'),
                ("Content-Length", str(len(xlsx_data))),
            ])
        except Exception as e:
            _logger.exception("Error exportando métricas de Traslados")
            return request.make_response(str(e), status=500)

    def _render_xlsx(self, data, company, period):
        """Arma el libro: resumen arriba de cada hoja y una tabla por pestaña."""
        sheets = [
            ("Pendientes", data["pending"],
             ["Número", "Estado", "Origen", "Destino", "Fecha", "Días en camino", "Unidades", "Costo", "Venta"],
             ["name", "status", "origen", "destino", "fecha", "days", "units", "cost", "sale"]),
            ("Rutas", data["routes"],
             ["Origen", "Destino", "Traslados", "Unidades", "Costo", "Venta", "Diferencia (u)",
              "Diferencia a costo", "Demora prom. (h)", "Demora máx. (h)"],
             ["origen", "destino", "transfers", "units", "cost", "sale", "diff", "diff_cost",
              "avg_hours", "max_hours"]),
            ("Diferencias", data["diffs"],
             ["Número", "Fecha", "Ruta", "Producto", "Enviado", "Recibido", "Diferencia",
              "Diferencia a costo", "Estado"],
             ["name", "fecha", "route", "producto", "sent", "received", "diff", "diff_cost", "status"]),
            ("Productos", data["products"],
             ["Producto", "Categoría", "Traslados", "Rutas", "Unidades", "Costo", "Venta", "Diferencia (u)"],
             ["producto", "categoria", "transfers", "routes", "units", "cost", "sale", "diff"]),
        ]
        money_keys = {"cost", "sale", "diff_cost"}
        totals = data["totals"]
        company_label = ", ".join(_to_list(company)) or "Todas las empresas"

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        fmt_title = workbook.add_format({"bold": True, "font_size": 12})
        fmt_header = workbook.add_format({
            "bold": True, "bg_color": "#1e293b", "font_color": "#ffffff",
            "border": 1, "align": "center", "valign": "vcenter"})
        fmt_text = workbook.add_format({"border": 1})
        fmt_money = workbook.add_format({"border": 1, "num_format": "#,##0.00"})
        fmt_num = workbook.add_format({"border": 1, "num_format": "#,##0.##"})

        for title, rows, headers, keys in sheets:
            sheet = workbook.add_worksheet(title)
            sheet.set_column(0, len(headers) - 1, 18)
            sheet.write(0, 0, f"Traslados · {title}", fmt_title)
            sheet.write(1, 0, f"{company_label} · últimos {period} días (abiertos siempre) · "
                              f"costo ${totals['cost']:,.2f} · venta ${totals['sale']:,.2f}")
            for col, header in enumerate(headers):
                sheet.write(3, col, header, fmt_header)
            for idx, row in enumerate(rows):
                for col, key in enumerate(keys):
                    value = row.get(key)
                    if key == "status":
                        sheet.write_string(4 + idx, col, STATUS_LABELS.get(value, ""), fmt_text)
                    elif isinstance(value, (int, float)):
                        sheet.write_number(4 + idx, col, value, fmt_money if key in money_keys else fmt_num)
                    else:
                        sheet.write_string(4 + idx, col, "" if value is None else str(value), fmt_text)
            sheet.freeze_panes(4, 0)
        workbook.close()
        return output.getvalue()
