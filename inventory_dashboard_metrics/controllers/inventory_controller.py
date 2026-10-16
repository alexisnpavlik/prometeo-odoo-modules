# -*- coding: utf-8 -*-
import io
import logging
import math
from datetime import datetime

import xlsxwriter

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)

PERIODS = (30, 60, 90, 180, 365)
TARGET_DAYS = (30, 60, 90, 120, 180)
DEFAULT_PERIOD = 90
DEFAULT_TARGET = 90
LEAD_DAYS = (3, 7, 15, 30)
DEFAULT_LEAD = 7
NO_VENDOR = "Sin proveedor"
BUY_COVER_MIN, BUY_COVER_MAX, DEFAULT_BUY_COVER = 7, 180, 30
LOW_COVER_DAYS = 15
MAX_TABLE_ROWS = 20000
UNCATEGORIZED = "Sin categorizar"
GENERIC_CATEGORIES = ("all", "todos", "all / saleable")


OVER_SORTS = {
    "excess": lambda r: -r["excess_value"],
    "value": lambda r: -r["value"],
    "stock": lambda r: -r["stock"],
    "idle": lambda r: -(r["days_since_sale"] if r["days_since_sale"] is not None else 10 ** 9),
}
STATUS_LABELS = {
    "sin_venta": "Sin ventas", "sobrestock": "Sobrestock",
    "sin_stock": "Sin stock", "por_agotarse": "Por agotarse",
    "urgente": "Urgente", "normal": "Normal",
}


def _round_units(value):
    """Redondeo comercial: 4,2 -> 4 y 4,5 -> 5. Hacia arriba compraba de más en productos de poca venta."""
    return int(math.floor(value + 0.5))


def _to_int(value, allowed, default):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value in allowed else default


class InventoryMetricsController(http.Controller):

    def _check_access(self):
        if not request.env.user.has_group('inventory_dashboard_metrics.group_inventory_metrics_user'):
            raise AccessError("No tienes permisos para acceder a las métricas de inventario.")

    def _get_lang(self):
        return request.env.context.get('lang') or 'es_AR'

    def _resolve_companies(self, company):
        """Empresas a consultar: la elegida (si el usuario puede verla) o todas las permitidas."""
        allowed = tuple(request.env.companies.ids)
        if company and company != 'all':
            request.env.cr.execute("SELECT id FROM res_company WHERE name = %s AND id IN %s",
                                   (company, allowed or (0,)))
            row = request.env.cr.fetchone()
            if row:
                return (row[0],)
        return allowed

    @http.route('/inventory_dashboard_metrics/filters', type='json', auth='user')
    def get_filters(self, **kwargs):
        self._check_access()
        allowed_companies = tuple(request.env.companies.ids)
        if not allowed_companies:
            return {"companies": []}
        request.env.cr.execute(
            "SELECT name FROM res_company WHERE id IN %s ORDER BY name", (allowed_companies,))
        return {"companies": [r[0] for r in request.env.cr.fetchall() if r[0]]}

    def _fetch_product_rows(self, companies, period, lang):
        """Una fila por producto almacenable: stock actual, valor, ventas del período y última venta.

        Venta = movimiento hecho de ubicación interna a cliente (incluye POS).
        """
        cr = request.env.cr
        cr.execute("""
            WITH stock AS (
                SELECT sq.product_id,
                       SUM(sq.quantity) AS stock,
                       SUM(sq.quantity * COALESCE(
                           (pp.standard_price->>(sq.company_id::text))::numeric,
                           (pp.standard_price->>'1')::numeric, 0.0)) AS value
                FROM stock_quant sq
                JOIN stock_location sl ON sl.id = sq.location_id
                     AND sl.usage = 'internal' AND sl.active = TRUE
                JOIN product_product pp ON pp.id = sq.product_id
                WHERE sq.company_id IN %(companies)s
                GROUP BY sq.product_id
            ),
            sales AS (
                SELECT sm.product_id,
                       SUM(sm.product_qty) FILTER (
                           WHERE sm.date >= NOW() - %(period)s * INTERVAL '1 day') AS qty_period,
                       MAX(sm.date) AS last_sale
                FROM stock_move sm
                JOIN stock_location sls ON sls.id = sm.location_id AND sls.usage = 'internal'
                JOIN stock_location sld ON sld.id = sm.location_dest_id AND sld.usage = 'customer'
                JOIN product_product pp ON pp.id = sm.product_id
                WHERE sm.state = 'done' AND sm.company_id IN %(companies)s
                GROUP BY sm.product_id
            )
            SELECT pp.id AS product_id,
                   pt.id AS tmpl_id,
                   COALESCE((pp.standard_price->>%(first_company)s)::numeric,
                            (pp.standard_price->>'1')::numeric, 0.0) AS cost,
                   COALESCE(pt.name->>%(lang)s, pt.name->>'en_US') AS producto,
                   pc.name AS categoria,
                   COALESCE(st.stock, 0.0) AS stock,
                   COALESCE(st.value, 0.0) AS value,
                   COALESCE(sa.qty_period, 0.0) AS qty_period,
                   sa.last_sale
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            LEFT JOIN stock st ON st.product_id = pp.id
            LEFT JOIN sales sa ON sa.product_id = pp.id
            WHERE pp.active = TRUE AND pt.active = TRUE
              AND pt.type = 'consu' AND pt.is_storable = TRUE
              AND (st.product_id IS NOT NULL OR sa.product_id IS NOT NULL)
        """, {"companies": companies, "period": period, "lang": lang,
                    "first_company": str(companies[0])})
        return cr.dictfetchall()

    def _fetch_suppliers(self, companies):
        """Proveedor principal por plantilla: primera línea vigente de la ficha (misma regla que Odoo)."""
        cr = request.env.cr
        cr.execute("""
            SELECT DISTINCT ON (si.product_tmpl_id)
                   si.product_tmpl_id, rp.name AS vendor, si.price, si.delay, si.min_qty
            FROM product_supplierinfo si
            JOIN res_partner rp ON rp.id = si.partner_id
            WHERE (si.company_id IS NULL OR si.company_id IN %s)
              AND (si.date_start IS NULL OR si.date_start <= CURRENT_DATE)
              AND (si.date_end IS NULL OR si.date_end >= CURRENT_DATE)
            ORDER BY si.product_tmpl_id, si.sequence, si.id
        """, (companies,))
        return {r["product_tmpl_id"]: r for r in cr.dictfetchall()}

    def _fetch_incoming(self, companies):
        """Unidades pedidas en órdenes confirmadas que todavía no se recibieron."""
        cr = request.env.cr
        cr.execute("""
            SELECT pol.product_id, SUM(pol.product_qty - pol.qty_received) AS qty
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            WHERE po.state = 'purchase' AND po.company_id IN %s
              AND pol.product_id IS NOT NULL AND pol.product_qty > pol.qty_received
            GROUP BY pol.product_id
        """, (companies,))
        return {r["product_id"]: float(r["qty"]) for r in cr.dictfetchall()}

    def _attach_vendor(self, rows, suppliers):
        for r in rows:
            sup = suppliers.get(r["tmpl_id"])
            r["vendor"] = sup["vendor"] if sup else NO_VENDOR
        return rows

    def _purchase_candidates(self, rows, suppliers, incoming, lead_default):
        """Productos con ventas en el período, con todo lo necesario para calcular cuánto comprar."""
        result = []
        for r in rows:
            if r["daily"] <= 0:
                continue
            sup = suppliers.get(r["tmpl_id"])
            lead = int(sup["delay"]) if sup and sup["delay"] and sup["delay"] > 0 else lead_default
            pending = incoming.get(r["product_id"], 0.0)
            days_left = (max(r["stock"], 0.0) + pending) / r["daily"]
            price = float(sup["price"]) if sup and sup["price"] and sup["price"] > 0 else float(r["cost"] or 0.0)
            result.append({
                "product_id": r["product_id"],
                "producto": r["producto"],
                "categoria": r["categoria"],
                "vendor": sup["vendor"] if sup else NO_VENDOR,
                "stock": round(r["stock"], 2),
                "incoming": round(pending, 2),
                "sold": round(r["qty_period"], 2),
                "daily": r["daily"],
                "days_left": int(round(days_left)),
                "lead": lead,
                "supplier_min": int(math.ceil(sup["min_qty"])) if sup and sup["min_qty"] else 0,
                "price": round(price, 2),
                "status": "urgente" if days_left < lead else "normal",
            })
        return result

    def _purchase_rows(self, candidates, cover):
        """Comprar = venta diaria x (plazo + días a cubrir) - stock - lo ya pedido. Misma cuenta que el JS."""
        result = []
        for c in candidates:
            qty = _round_units(c["daily"] * (c["lead"] + cover) - max(c["stock"], 0.0) - c["incoming"])
            if qty <= 0:
                continue
            # El mínimo del proveedor se informa pero no se impone: forzarlo genera sobrestock
            result.append(dict(c, qty=qty, total=round(qty * c["price"], 2),
                               min_qty=c["supplier_min"] if c["supplier_min"] > qty else 0))
        result.sort(key=lambda r: (r["status"] != "urgente", r["vendor"] == NO_VENDOR, r["vendor"], -r["total"]))
        return result

    def _classify(self, rows, period, target):
        """Agrega por producto: cobertura, estado (sin_venta/sobrestock/ok) y excedente."""
        now = datetime.now()
        for r in rows:
            stock = float(r["stock"] or 0.0)
            qty = float(r["qty_period"] or 0.0)
            r["stock"] = stock
            r["qty_period"] = qty
            r["categoria"] = r["categoria"] if r["categoria"] and r["categoria"].lower() not in GENERIC_CATEGORIES \
                else UNCATEGORIZED
            r["daily"] = qty / period
            r["value"] = max(float(r["value"] or 0.0), 0.0) if stock > 0 else 0.0
            unit_cost = r["value"] / stock if stock > 0 else 0.0
            r["cover"] = stock / r["daily"] if stock > 0 and r["daily"] > 0 else None
            r["days_since_sale"] = (now - r["last_sale"]).days if r["last_sale"] else None

            r["status"] = "ok"
            r["excess_units"] = 0.0
            if stock > 0:
                if qty <= 0:
                    r["status"] = "sin_venta"
                    r["excess_units"] = stock
                elif r["cover"] > target:
                    r["status"] = "sobrestock"
                    r["excess_units"] = stock - r["daily"] * target
            r["excess_value"] = r["excess_units"] * unit_cost
        return rows

    def _overstock_rows(self, rows):
        flagged = [r for r in rows if r["status"] in ("sin_venta", "sobrestock")]
        flagged.sort(key=lambda r: (r["excess_value"], r["stock"]), reverse=True)
        return len(flagged), [{
            "product_id": r["product_id"],
            "producto": r["producto"],
            "categoria": r["categoria"],
            "vendor": r["vendor"],
            "stock": round(r["stock"], 2),
            "sold": round(r["qty_period"], 2),
            "daily": round(r["daily"], 2),
            "cover": int(round(r["cover"])) if r["cover"] is not None else None,
            "last_sale": r["last_sale"].strftime("%d/%m/%Y") if r["last_sale"] else None,
            "days_since_sale": r["days_since_sale"],
            "value": round(r["value"], 2),
            "excess_value": round(r["excess_value"], 2),
            "status": r["status"],
        } for r in flagged[:MAX_TABLE_ROWS]]

    def _restock_rows(self, rows):
        """Productos con demanda que se quedaron sin stock o les quedan pocos días."""
        urgent = [r for r in rows if r["qty_period"] > 0 and (r["stock"] <= 0 or (
            r["cover"] is not None and r["cover"] <= LOW_COVER_DAYS))]
        urgent.sort(key=lambda r: (r["cover"] if r["cover"] is not None else -1, -r["daily"]))
        return len(urgent), [{
            "product_id": r["product_id"],
            "producto": r["producto"],
            "categoria": r["categoria"],
            "vendor": r["vendor"],
            "stock": round(r["stock"], 2),
            "sold": round(r["qty_period"], 2),
            "daily": round(r["daily"], 2),
            "cover": int(round(r["cover"])) if r["cover"] is not None else 0,
            "status": "sin_stock" if r["stock"] <= 0 else "por_agotarse",
        } for r in urgent[:MAX_TABLE_ROWS]]

    @http.route('/inventory_dashboard_metrics/inventory', type='json', auth='user')
    def get_inventory(self, company='all', **kwargs):
        self._check_access()
        period = _to_int(kwargs.get('period'), PERIODS, DEFAULT_PERIOD)
        target = _to_int(kwargs.get('target'), TARGET_DAYS, DEFAULT_TARGET)
        lang = self._get_lang()
        companies = self._resolve_companies(company)

        if not companies:
            return {"overstock_total": 0, "excess_value": 0, "overstock": [], "restock_total": 0, "restock": []}

        rows = self._classify(self._fetch_product_rows(companies, period, lang), period, target)
        self._attach_vendor(rows, self._fetch_suppliers(companies))
        overstock_total, overstock = self._overstock_rows(rows)
        restock_total, restock = self._restock_rows(rows)

        return {
            "overstock_total": overstock_total,
            "excess_value": round(sum(r["excess_value"] for r in rows if r["stock"] > 0), 2),
            "overstock": overstock,
            "restock_total": restock_total,
            "restock": restock,
        }

    @http.route('/inventory_dashboard_metrics/purchase', type='json', auth='user')
    def get_purchase(self, company='all', **kwargs):
        self._check_access()
        period = _to_int(kwargs.get('period'), PERIODS, DEFAULT_PERIOD)
        target = _to_int(kwargs.get('target'), TARGET_DAYS, DEFAULT_TARGET)
        lead = _to_int(kwargs.get('lead'), LEAD_DAYS, DEFAULT_LEAD)
        companies = self._resolve_companies(company)
        if not companies:
            return {"rows": []}
        rows = self._classify(self._fetch_product_rows(companies, period, self._get_lang()), period, target)
        return {"rows": self._purchase_candidates(
            rows, self._fetch_suppliers(companies), self._fetch_incoming(companies), lead)}

    @http.route('/inventory_dashboard_metrics/export', type='http', auth='user')
    def export_xlsx(self, table='overstock', company='all', period=None, target=None,
                    status='all', category='all', search='', sort='excess',
                    lead=None, vendor='all', cover=None, **kwargs):
        """Exporta a Excel la tabla activa con los mismos filtros que ve el usuario."""
        try:
            self._check_access()
            period = _to_int(period, PERIODS, DEFAULT_PERIOD)
            target = _to_int(target, TARGET_DAYS, DEFAULT_TARGET)
            companies = self._resolve_companies(company)
            rows = self._classify(
                self._fetch_product_rows(companies, period, self._get_lang()), period, target)

            suppliers = self._fetch_suppliers(companies)
            self._attach_vendor(rows, suppliers)

            if table == 'purchase':
                lead = _to_int(lead, LEAD_DAYS, DEFAULT_LEAD)
                cover = _to_int(cover, range(BUY_COVER_MIN, BUY_COVER_MAX + 1), DEFAULT_BUY_COVER)
                data = self._purchase_rows(
                    self._purchase_candidates(rows, suppliers, self._fetch_incoming(companies), lead), cover)
                title = f"Recomendador de compra ({cover} días)"
                headers = ["Producto", "Categoría", "Proveedor", "Stock", "Ya pedido", f"Vendidas ({period} días)", "Venta/día",
                           "Alcanza para (días)", "Plazo (días)", "Comprar", "Mínimo del proveedor",
                           "Precio", "Total", "Prioridad"]
                keys = ["producto", "categoria", "vendor", "stock", "incoming", "sold", "daily", "days_left",
                        "lead", "qty", "min_qty", "price", "total", "status"]
                data = [r for r in data if vendor in ('', 'all') or r["vendor"] == vendor]
            elif table == 'restock':
                _total, data = self._restock_rows(rows)
                title = "Productos por reponer"
                headers = ["Producto", "Categoría", "Proveedor", "Stock", f"Vendidas ({period} días)", "Venta/día",
                           "Alcanza para (días)", "Estado"]
                keys = ["producto", "categoria", "vendor", "stock", "sold", "daily", "cover", "status"]
            else:
                _total, data = self._overstock_rows(rows)
                data.sort(key=OVER_SORTS.get(sort, OVER_SORTS["excess"]))
                title = "Mucho stock y poca venta"
                headers = ["Producto", "Categoría", "Proveedor", "Stock", f"Vendidas ({period} días)", "Venta/día", "Alcanza para (días)",
                           "Última venta", "Valor", "De más", "Estado"]
                keys = ["producto", "categoria", "vendor", "stock", "sold", "daily", "cover", "last_sale",
                        "value", "excess_value", "status"]

            query = (search or '').lower().strip()
            data = [r for r in data
                    if (status in ('', 'all') or r["status"] == status)
                    and (category in ('', 'all') or r["categoria"] == category)
                    and (not query or query in r["producto"].lower())]

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            fmt_title = workbook.add_format({'bold': True, 'font_size': 12})
            fmt_header = workbook.add_format({
                'bold': True, 'bg_color': '#1e293b', 'font_color': '#ffffff',
                'border': 1, 'align': 'center', 'valign': 'vcenter'})
            fmt_text = workbook.add_format({'border': 1})
            fmt_money = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
            fmt_num = workbook.add_format({'border': 1, 'num_format': '#,##0.##'})
            money_keys = {"value", "excess_value", "price", "total"}

            sheet = workbook.add_worksheet(title[:31])
            sheet.set_column(0, 0, 50)
            sheet.set_column(1, 1, 24)
            sheet.set_column(2, len(headers) - 1, 16)
            company_label = company if company and company != 'all' else 'Todas las empresas'
            sheet.write(0, 0, title, fmt_title)
            sheet.write(1, 0, f"{company_label} · ventas de los últimos {period} días · cobertura objetivo {target} días")
            for col, header in enumerate(headers):
                sheet.write(3, col, header, fmt_header)
            for idx, row in enumerate(data):
                for col, key in enumerate(keys):
                    value = row.get(key)
                    if key == "status":
                        sheet.write_string(4 + idx, col, STATUS_LABELS.get(value, ''), fmt_text)
                    elif key == "daily":
                        sheet.write_number(4 + idx, col, round(value, 2), fmt_num)
                    elif isinstance(value, (int, float)):
                        sheet.write_number(4 + idx, col, value, fmt_money if key in money_keys else fmt_num)
                    else:
                        sheet.write_string(4 + idx, col, value or ('Nunca' if key == "last_sale" else ''), fmt_text)
            sheet.freeze_panes(4, 1)
            workbook.close()
            xlsx_data = output.getvalue()
            output.close()

            filename = f"{table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            return request.make_response(xlsx_data, headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
                ('Content-Length', str(len(xlsx_data))),
            ])
        except Exception as e:
            _logger.exception("Error exportando métricas de inventario")
            return request.make_response(str(e), status=500)
