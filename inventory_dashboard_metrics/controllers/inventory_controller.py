# -*- coding: utf-8 -*-
import io
import json
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
NO_VENDOR = "Sin proveedor"
BUY_COVER_MIN, BUY_COVER_MAX, DEFAULT_BUY_COVER = 7, 180, 30
LOW_COVER_DAYS = 15
# Un producto con menos historia que el período se promedia sobre sus días reales, con este mínimo
MIN_HISTORY_DAYS = 7
# Decimales del promedio diario: el mismo valor redondeado se muestra y se usa en la cuenta
DAILY_DECIMALS = 3
# Filas por estado que viajan a la tabla: con todas las sucursales son ~60 mil (20 MB). Las tarjetas
# y los totales se calculan sobre todas en el servidor; el Excel también las lleva todas.
MAX_ROWS_PER_STATUS = 3000
TOP_BRANCHES = 3
UNCATEGORIZED = "Sin categorizar"
GENERIC_CATEGORIES = ("all", "todos", "all / saleable")


OVER_SORTS = {
    "excess": lambda r: -r["excess_value"],
    "cover": lambda r: -(r["cover"] if r["cover"] is not None else 10 ** 9),
    "stock": lambda r: -r["stock"],
}
STATUS_LABELS = {
    "sin_venta": "Sin ventas", "sobrestock": "Sobrestock",
    "sin_stock": "Sin stock", "por_agotarse": "Por agotarse",
    "urgente": "Urgente", "normal": "Normal",
}


def _round_units(value):
    """Redondeo comercial: 4,2 -> 4 y 4,5 -> 5. Hacia arriba compraba de más en productos de poca venta."""
    return int(math.floor(value + 0.5))


def _to_list(value):
    """Filtro multi-selección: lista, JSON de lista o valor suelto. Vacío o 'all' = sin filtro."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, str):
        value = [value]
    return [v for v in (value or []) if v and v != 'all']


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
        """Empresas a consultar: las elegidas (que el usuario pueda ver) o todas las permitidas."""
        allowed = tuple(request.env.companies.ids)
        names = _to_list(company)
        if names and allowed:
            request.env.cr.execute("SELECT id FROM res_company WHERE name IN %s AND id IN %s ORDER BY id",
                                   (tuple(names), allowed))
            ids = tuple(r[0] for r in request.env.cr.fetchall())
            if ids:
                return ids
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

    def _fetch_product_rows(self, companies, period, lang, by_branch=False):
        """Una fila por producto almacenable: stock actual, valor, ventas del período y última venta.

        Venta = movimiento hecho de ubicación interna a cliente (incluye POS).
        by_branch: una fila por producto y empresa. Sin él se junta todo en una fila (red como un solo
        depósito): el stock de una sucursal tapaba el faltante de otra y el del depósito inflaba el sobrestock.
        """
        cr = request.env.cr
        # Columna de agrupación: la empresa real o una constante (la primera) para el modo junto
        sq_co, sm_co = ("sq.company_id", "sm.company_id") if by_branch else ("%(first_id)s", "%(first_id)s")
        cr.execute(f"""
            WITH stock AS (
                SELECT sq.product_id, {sq_co} AS company_id,
                       SUM(sq.quantity) AS stock,
                       SUM(sq.quantity * COALESCE(
                           (pp.standard_price->>(sq.company_id::text))::numeric,
                           (pp.standard_price->>'1')::numeric, 0.0)) AS value
                FROM stock_quant sq
                JOIN stock_location sl ON sl.id = sq.location_id
                     AND sl.usage = 'internal' AND sl.active = TRUE
                JOIN product_product pp ON pp.id = sq.product_id
                WHERE sq.company_id IN %(companies)s
                GROUP BY 1, 2
            ),
            sales AS (
                SELECT sm.product_id, {sm_co} AS company_id,
                       SUM(sm.product_qty) FILTER (
                           WHERE sm.date >= NOW() - %(period)s * INTERVAL '1 day') AS qty_period,
                       MAX(sm.date) AS last_sale
                FROM stock_move sm
                JOIN stock_location sls ON sls.id = sm.location_id AND sls.usage = 'internal'
                JOIN stock_location sld ON sld.id = sm.location_dest_id AND sld.usage = 'customer'
                WHERE sm.state = 'done' AND sm.company_id IN %(companies)s
                GROUP BY 1, 2
            ),
            first_move AS (
                SELECT sm.product_id, {sm_co} AS company_id, MIN(sm.date) AS first_move
                FROM stock_move sm
                WHERE sm.state = 'done' AND sm.company_id IN %(companies)s
                GROUP BY 1, 2
            ),
            keys AS (
                SELECT product_id, company_id FROM stock
                UNION
                SELECT product_id, company_id FROM sales
            )
            SELECT pp.id AS product_id,
                   pt.id AS tmpl_id,
                   rc.name AS sucursal,
                   COALESCE((pp.standard_price->>(k.company_id::text))::numeric,
                            (pp.standard_price->>'1')::numeric, 0.0) AS cost,
                   COALESCE(pt.name->>%(lang)s, pt.name->>'en_US') AS producto,
                   pc.name AS categoria,
                   COALESCE(st.stock, 0.0) AS stock,
                   COALESCE(st.value, 0.0) AS value,
                   COALESCE(sa.qty_period, 0.0) AS qty_period,
                   sa.last_sale,
                   fm.first_move
            FROM keys k
            JOIN product_product pp ON pp.id = k.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN res_company rc ON rc.id = k.company_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            LEFT JOIN stock st ON st.product_id = k.product_id AND st.company_id = k.company_id
            LEFT JOIN sales sa ON sa.product_id = k.product_id AND sa.company_id = k.company_id
            LEFT JOIN first_move fm ON fm.product_id = k.product_id AND fm.company_id = k.company_id
            WHERE pp.active = TRUE AND pt.active = TRUE
              AND pt.type = 'consu' AND pt.is_storable = TRUE
        """, {"companies": companies, "period": period, "lang": lang, "first_id": companies[0]})
        return cr.dictfetchall()

    def _fetch_suppliers(self, companies):
        """Proveedor principal por plantilla: primera línea vigente de la ficha (misma regla que Odoo)."""
        cr = request.env.cr
        cr.execute("""
            SELECT DISTINCT ON (si.product_tmpl_id)
                   si.product_tmpl_id, rp.name AS vendor, si.price, si.min_qty
            FROM product_supplierinfo si
            JOIN res_partner rp ON rp.id = si.partner_id
            WHERE (si.company_id IS NULL OR si.company_id IN %s)
              AND (si.date_start IS NULL OR si.date_start <= CURRENT_DATE)
              AND (si.date_end IS NULL OR si.date_end >= CURRENT_DATE)
            ORDER BY si.product_tmpl_id, si.sequence, si.id
        """, (companies,))
        return {r["product_tmpl_id"]: r for r in cr.dictfetchall()}

    def _attach_vendor(self, rows, suppliers):
        for r in rows:
            sup = suppliers.get(r["tmpl_id"])
            r["vendor"] = sup["vendor"] if sup else NO_VENDOR
        return rows

    def _purchase_candidates(self, rows, suppliers):
        """Productos con ventas en el período, con todo lo necesario para calcular cuánto comprar."""
        result = []
        for r in rows:
            if r["daily"] <= 0:
                continue
            sup = suppliers.get(r["tmpl_id"])
            days_left = max(r["stock"], 0.0) / r["daily"]
            price = float(sup["price"]) if sup and sup["price"] and sup["price"] > 0 else float(r["cost"] or 0.0)
            result.append({
                "product_id": r["product_id"],
                "producto": r["producto"],
                "categoria": r["categoria"],
                "vendor": sup["vendor"] if sup else NO_VENDOR,
                "stock": round(r["stock"], 2),
                "sold": round(r["qty_period"], 2),
                "days": r["days"],
                "daily": r["daily"],
                "days_left": int(round(days_left)),
                "supplier_min": int(math.ceil(sup["min_qty"])) if sup and sup["min_qty"] else 0,
                "price": round(price, 2),
                # Mismo criterio que "Por reponer": sin stock o con 15 días o menos
                "status": "urgente" if days_left <= LOW_COVER_DAYS else "normal",
            })
        return result

    def _purchase_rows(self, candidates, cover):
        """Comprar = venta diaria x días a cubrir - stock. Misma cuenta que el JS."""
        result = []
        for c in candidates:
            # Stock negativo = venta sin entrada registrada, no un faltante real: se toma como 0
            # (sumarlo sugería comprar años de stock; en pantalla se marca "revisar")
            stock = max(c["stock"], 0.0)
            qty = _round_units(c["daily"] * cover - stock)
            if qty <= 0:
                continue
            # El mínimo del proveedor se informa pero no se impone: forzarlo genera sobrestock
            result.append(dict(c, qty=qty, total=round(qty * c["price"], 2),
                               min_qty=c["supplier_min"] if c["supplier_min"] > qty else 0,
                               # Días que cubriría el stock después de comprar
                               days_after=_round_units((stock + qty) / c["daily"])))
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
            # Se promedia sobre el período, salvo que el producto tenga menos historia (base o producto
            # nuevos): dividir siempre por el período subestimaba la venta (kiosco: 9 días de datos / 90).
            history = (now - r["first_move"]).total_seconds() / 86400 if r["first_move"] else period
            r["days"] = int(round(min(period, max(history, MIN_HISTORY_DAYS))))
            r["daily"] = round(qty / r["days"], DAILY_DECIMALS)
            r["value"] = max(float(r["value"] or 0.0), 0.0) if stock > 0 else 0.0
            unit_cost = r["value"] / stock if stock > 0 else 0.0
            r["cover"] = stock / r["daily"] if stock > 0 and r["daily"] > 0 else None
            r["days_since_sale"] = (now - r["last_sale"]).days if r["last_sale"] else None

            r["status"] = "ok"
            r["excess_units"] = 0.0
            if stock > 0:
                if r["daily"] <= 0:
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
            "sucursal": r["sucursal"],
            "categoria": r["categoria"],
            "vendor": r["vendor"],
            "stock": round(r["stock"], 2),
            "sold": round(r["qty_period"], 2),
            "days": r["days"],
            "daily": r["daily"],
            "cover": int(round(r["cover"])) if r["cover"] is not None else None,
            "last_sale": r["last_sale"].strftime("%d/%m/%Y") if r["last_sale"] else None,
            "days_since_sale": r["days_since_sale"],
            "value": round(r["value"], 2),
            "excess_value": round(r["excess_value"], 2),
            "status": r["status"],
        } for r in flagged]

    def _restock_rows(self, rows):
        """Productos con demanda que se quedaron sin stock o les quedan pocos días."""
        urgent = [r for r in rows if r["daily"] > 0 and (r["stock"] <= 0 or (
            r["cover"] is not None and r["cover"] <= LOW_COVER_DAYS))]
        urgent.sort(key=lambda r: (r["cover"] if r["cover"] is not None else -1, -r["daily"]))
        return len(urgent), [{
            "product_id": r["product_id"],
            "producto": r["producto"],
            "sucursal": r["sucursal"],
            "categoria": r["categoria"],
            "vendor": r["vendor"],
            "stock": round(r["stock"], 2),
            "sold": round(r["qty_period"], 2),
            "days": r["days"],
            "daily": r["daily"],
            "cover": int(round(r["cover"])) if r["cover"] is not None else 0,
            "status": "sin_stock" if r["stock"] <= 0 else "por_agotarse",
        } for r in urgent]

    def _summary(self, rows):
        """Por estado: cantidad, plata de más y las sucursales con más casos (si hay más de una)."""
        summary = {}
        for r in rows:
            item = summary.setdefault(r["status"], {"count": 0, "amount": 0.0, "branches": {}})
            item["count"] += 1
            item["amount"] += r.get("excess_value") or 0.0
            item["branches"][r["sucursal"]] = item["branches"].get(r["sucursal"], 0) + 1
        for item in summary.values():
            branches = sorted(item["branches"].items(), key=lambda b: -b[1])
            item["branches"] = [{"name": n, "count": c} for n, c in branches[:TOP_BRANCHES]] \
                if len(branches) > 1 else []
            item["amount"] = round(item["amount"], 2)
        return summary

    @staticmethod
    def _cap_per_status(rows):
        """Primeras filas de cada estado, respetando el orden que ya traen."""
        seen = {}
        result = []
        for r in rows:
            seen[r["status"]] = seen.get(r["status"], 0) + 1
            if seen[r["status"]] <= MAX_ROWS_PER_STATUS:
                result.append(r)
        return result

    @http.route('/inventory_dashboard_metrics/inventory', type='json', auth='user')
    def get_inventory(self, company='all', category='all', vendor='all', product='all', **kwargs):
        self._check_access()
        period = _to_int(kwargs.get('period'), PERIODS, DEFAULT_PERIOD)
        target = _to_int(kwargs.get('target'), TARGET_DAYS, DEFAULT_TARGET)
        lang = self._get_lang()
        companies = self._resolve_companies(company)

        if not companies:
            return {"overstock": [], "restock": [], "summary": {},
                    "options": {"categories": [], "vendors": [], "products": []}}

        # Una fila por producto y sucursal: juntar la red escondía faltantes y sumaba el depósito
        rows = self._classify(self._fetch_product_rows(companies, period, lang, by_branch=True), period, target)
        self._attach_vendor(rows, self._fetch_suppliers(companies))
        _total, overstock = self._overstock_rows(rows)
        _total, restock = self._restock_rows(rows)

        # Las opciones de los filtros salen de todas las filas, antes de filtrar
        flagged = overstock + restock
        options = {
            "categories": sorted({r["categoria"] for r in flagged}),
            "vendors": sorted({r["vendor"] for r in flagged}),
            "products": sorted({(r["producto"], r["categoria"]) for r in flagged}),
        }
        category, vendor, product = _to_list(category), _to_list(vendor), _to_list(product)

        def keep(r):
            return ((not category or r["categoria"] in category)
                    and (not vendor or r["vendor"] in vendor)
                    and (not product or r["producto"] in product))

        overstock = [r for r in overstock if keep(r)]
        restock = [r for r in restock if keep(r)]
        return {
            "summary": self._summary(overstock + restock),
            "options": options,
            "overstock": self._cap_per_status(overstock),
            "restock": self._cap_per_status(restock),
        }

    @http.route('/inventory_dashboard_metrics/purchase', type='json', auth='user')
    def get_purchase(self, company='all', **kwargs):
        self._check_access()
        period = _to_int(kwargs.get('period'), PERIODS, DEFAULT_PERIOD)
        target = _to_int(kwargs.get('target'), TARGET_DAYS, DEFAULT_TARGET)
        companies = self._resolve_companies(company)
        if not companies:
            return {"rows": []}
        rows = self._classify(self._fetch_product_rows(companies, period, self._get_lang()), period, target)
        return {"rows": self._purchase_candidates(rows, self._fetch_suppliers(companies))}

    @http.route('/inventory_dashboard_metrics/export', type='http', auth='user')
    def export_xlsx(self, table='overstock', company='all', period=None, target=None,
                    status='all', category='all', product='all', sort='excess',
                    vendor='all', cover=None, **kwargs):
        """Exporta a Excel la tabla activa con los mismos filtros que ve el usuario."""
        try:
            self._check_access()
            period = _to_int(period, PERIODS, DEFAULT_PERIOD)
            target = _to_int(target, TARGET_DAYS, DEFAULT_TARGET)
            companies = self._resolve_companies(company)
            # Stock por sucursal; el recomendador de compra sigue con la red junta
            rows = self._classify(self._fetch_product_rows(
                companies, period, self._get_lang(), by_branch=table != 'purchase'), period, target)

            suppliers = self._fetch_suppliers(companies)
            self._attach_vendor(rows, suppliers)

            if table == 'purchase':
                cover = _to_int(cover, range(BUY_COVER_MIN, BUY_COVER_MAX + 1), DEFAULT_BUY_COVER)
                data = self._purchase_rows(self._purchase_candidates(rows, suppliers), cover)
                title = f"Recomendador de compra ({cover} días)"
                headers = ["Producto", "Categoría", "Proveedor", "Stock", f"Vendidas ({period} días)", "Días promediados", "Promedio de ventas por día",
                           "Alcanzaría para (días)", "Comprar", "Mínimo del proveedor",
                           "Precio", "Total", "Prioridad"]
                keys = ["producto", "categoria", "vendor", "stock", "sold", "days", "daily", "days_after",
                        "qty", "min_qty", "price", "total", "status"]
            elif table == 'restock':
                _total, data = self._restock_rows(rows)
                title = "Productos por reponer"
                headers = ["Producto", "Sucursal", "Categoría", "Proveedor", "Stock", f"Vendidas ({period} días)", "Días promediados", "Promedio de ventas por día",
                           "Alcanza para (días)", "Estado"]
                keys = ["producto", "sucursal", "categoria", "vendor", "stock", "sold", "days", "daily", "cover", "status"]
            else:
                _total, data = self._overstock_rows(rows)
                data.sort(key=OVER_SORTS.get(sort, OVER_SORTS["excess"]))
                title = "Mucho stock y poca venta"
                headers = ["Producto", "Sucursal", "Categoría", "Proveedor", "Stock", f"Vendidas ({period} días)", "Días promediados", "Promedio de ventas por día", "Alcanza para (días)",
                           "Estado"]
                keys = ["producto", "sucursal", "categoria", "vendor", "stock", "sold", "days", "daily", "cover", "status"]

            status, category, vendor, product = _to_list(status), _to_list(category), _to_list(vendor), _to_list(product)
            data = [r for r in data
                    if (not status or r["status"] in status)
                    and (not category or r["categoria"] in category)
                    and (not vendor or r["vendor"] in vendor)
                    and (not product or r["producto"] in product)]

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            fmt_title = workbook.add_format({'bold': True, 'font_size': 12})
            fmt_header = workbook.add_format({
                'bold': True, 'bg_color': '#1e293b', 'font_color': '#ffffff',
                'border': 1, 'align': 'center', 'valign': 'vcenter'})
            fmt_text = workbook.add_format({'border': 1})
            fmt_money = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
            fmt_num = workbook.add_format({'border': 1, 'num_format': '#,##0.##'})
            fmt_daily = workbook.add_format({'border': 1, 'num_format': '0.0'})
            money_keys = {"value", "excess_value", "price", "total"}

            sheet = workbook.add_worksheet(title[:31])
            sheet.set_column(0, 0, 50)
            sheet.set_column(1, 2, 24)
            sheet.set_column(3, len(headers) - 1, 16)
            company_label = ', '.join(_to_list(company)) or 'Todas las empresas'
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
                        sheet.write_number(4 + idx, col, value, fmt_daily)
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
