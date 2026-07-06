# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)

# Diferencia % máxima considerada dato válido: por encima se asume precio base
# no cargado o erróneo (ej. base $0.01 con precio real solo en la lista)
MAX_SANE_DIFF_PERCENT = 500.0
# Precio base mínimo para considerar la comparación (bases de relleno tipo $0.01)
MIN_SANE_BASE_PRICE = 1.0


class PricelistMetricsController(http.Controller):

    def _check_access(self):
        if not request.env.user.has_group('pricelist_management_metrics.group_pricelist_metrics_user'):
            raise AccessError("No tienes permisos para acceder a las métricas de precios por sucursal.")

    def _get_lang(self):
        return request.env.context.get('lang') or 'es_AR'

    def _get_pricelists(self, pricelist='all'):
        """Listas de precios activas de las compañías permitidas (una por sucursal/empresa)."""
        cr = request.env.cr
        lang = self._get_lang()
        allowed_companies = tuple(request.env.companies.ids)
        cr.execute("""
            SELECT pl.id,
                   COALESCE(pl.name->>%s, pl.name->>'en_US') AS nombre,
                   rc.name AS empresa
            FROM product_pricelist pl
            LEFT JOIN res_company rc ON rc.id = pl.company_id
            WHERE pl.active = TRUE
              AND (pl.company_id IS NULL OR pl.company_id IN %s)
            ORDER BY rc.name NULLS FIRST, 2
        """, (lang, allowed_companies))
        pricelists = cr.dictfetchall()
        if pricelist and pricelist != 'all':
            pricelists = [p for p in pricelists if p['id'] == int(pricelist)]
        return pricelists

    def _get_items(self, pricelist_ids, tmpl_ids=None):
        """Reglas de precio vigentes (producto o variante) para las listas indicadas.

        Devuelve un mapa {(pricelist_id, tmpl_id): item} priorizando reglas de variante
        sobre reglas de plantilla, igual que el motor de precios de Odoo.
        """
        cr = request.env.cr
        query = """
            SELECT pli.pricelist_id,
                   COALESCE(pp.product_tmpl_id, pli.product_tmpl_id) AS tmpl_id,
                   pli.applied_on,
                   pli.compute_price,
                   pli.fixed_price,
                   pli.percent_price
            FROM product_pricelist_item pli
            LEFT JOIN product_product pp ON pp.id = pli.product_id
            WHERE pli.pricelist_id IN %s
              AND pli.applied_on IN ('1_product', '0_product_variant')
              AND COALESCE(pli.min_quantity, 0) <= 1
              AND (pli.date_start IS NULL OR pli.date_start <= NOW())
              AND (pli.date_end IS NULL OR pli.date_end >= NOW())
        """
        params = [tuple(pricelist_ids)]
        if tmpl_ids is not None:
            if not tmpl_ids:
                return {}
            query += " AND COALESCE(pp.product_tmpl_id, pli.product_tmpl_id) IN %s"
            params.append(tuple(tmpl_ids))
        query += " ORDER BY pli.applied_on, pli.id"
        cr.execute(query, params)

        items = {}
        for row in cr.dictfetchall():
            key = (row['pricelist_id'], row['tmpl_id'])
            if key not in items:
                items[key] = row
        return items

    def _compute_item_price(self, item, base_price):
        """Precio resultante de una regla; None si la regla no es calculable (fórmula)."""
        if not item:
            return None
        if item['compute_price'] == 'fixed':
            return round(float(item['fixed_price'] or 0.0), 2)
        if item['compute_price'] == 'percentage':
            return round(base_price * (1 - float(item['percent_price'] or 0.0) / 100.0), 2)
        return None

    def _sane_diff(self, price, base):
        """Diferencia % contra el precio base; None si la comparación no es confiable."""
        if base < MIN_SANE_BASE_PRICE:
            return None
        diff = round((price - base) / base * 100.0, 2)
        if abs(diff) > MAX_SANE_DIFF_PERCENT:
            return None
        return diff

    def _build_template_where(self, category='all', product='all', search=None):
        lang = self._get_lang()
        where_clause = "pt.active = TRUE AND pt.sale_ok = TRUE"
        params = []
        if category and category != 'all':
            where_clause += " AND ic.name = %s"
            params.append(category)
        if product and product != 'all':
            where_clause += " AND COALESCE(pt.name->>%s, pt.name->>'en_US') = %s"
            params.extend([lang, product])
        if search:
            where_clause += " AND LOWER(COALESCE(pt.name->>%s, pt.name->>'en_US')) LIKE %s"
            params.extend([lang, f"%{search.lower()}%"])
        return where_clause, params

    @http.route('/pricelist_management_metrics/filters', type='json', auth='user')
    def get_filters(self, **kwargs):
        self._check_access()
        cr = request.env.cr
        lang = self._get_lang()

        # 1. Listas de precios (sucursales)
        pricelists = self._get_pricelists()

        # 2. Categorías
        cr.execute("""
            SELECT DISTINCT ic.name
            FROM product_category ic
            WHERE LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
            ORDER BY ic.name
        """)
        categories = [r[0] for r in cr.fetchall() if r[0]]

        # 3. Productos (traducido dinámicamente)
        cr.execute("""
            SELECT DISTINCT COALESCE(pt.name->>%s, pt.name->>'en_US')
            FROM product_template pt
            WHERE pt.active = TRUE AND pt.sale_ok = TRUE
            ORDER BY 1
        """, (lang,))
        products = [r[0] for r in cr.fetchall() if r[0]]

        # 4. Mapa categoría -> productos
        cr.execute("""
            SELECT DISTINCT ic.name, COALESCE(pt.name->>%s, pt.name->>'en_US')
            FROM product_template pt
            JOIN product_category ic ON ic.id = pt.categ_id
            WHERE LOWER(ic.name) NOT IN ('all', 'todos', 'all / saleable')
              AND pt.active = TRUE AND pt.sale_ok = TRUE
            ORDER BY ic.name, 2
        """, (lang,))
        products_by_category = {}
        for cat, prod in cr.fetchall():
            if cat and prod:
                products_by_category.setdefault(cat, []).append(prod)

        return {
            "pricelists": pricelists,
            "categories": categories,
            "products": products,
            "products_by_category": products_by_category,
        }

    @http.route('/pricelist_management_metrics/price_table', type='json', auth='user')
    def get_price_table(self, category='all', product='all', search=None, pricelist='all', only_diff=False, page=1, per_page=15, **kwargs):
        """Tabla comparativa paginada: precio base vs precio de cada lista/sucursal."""
        self._check_access()
        cr = request.env.cr
        lang = self._get_lang()

        pricelists = self._get_pricelists(pricelist)
        columns = [{"id": p["id"], "nombre": p["nombre"], "empresa": p["empresa"]} for p in pricelists]
        empty = {"columns": columns, "rows": [], "page": 1, "pages": 1, "total": 0}
        if not pricelists:
            return empty
        pl_ids = tuple(p["id"] for p in pricelists)

        where_clause, params = self._build_template_where(category, product, search)
        if only_diff:
            where_clause += """ AND EXISTS (
                SELECT 1 FROM product_pricelist_item pli2
                LEFT JOIN product_product pp2 ON pp2.id = pli2.product_id
                WHERE COALESCE(pp2.product_tmpl_id, pli2.product_tmpl_id) = pt.id
                  AND pli2.pricelist_id IN %s
                  AND pli2.applied_on IN ('1_product', '0_product_variant')
                  AND COALESCE(pli2.min_quantity, 0) <= 1
                  AND (pli2.date_start IS NULL OR pli2.date_start <= NOW())
                  AND (pli2.date_end IS NULL OR pli2.date_end >= NOW())
            )"""
            params.append(pl_ids)

        # 1. Contar total de filas para la paginación
        count_query = f"""
            SELECT COUNT(*)
            FROM product_template pt
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE {where_clause}
        """
        cr.execute(count_query, params)
        total_rows = cr.fetchone()[0] or 0

        per_page = int(per_page or 15)
        page = int(page or 1)
        total_pages = max(1, (total_rows + per_page - 1) // per_page)
        offset = (page - 1) * per_page

        # 2. Consultar productos paginados
        rows_query = f"""
            SELECT pt.id,
                   COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                   COALESCE(ic.name, 'Sin categoría')        AS categoria,
                   COALESCE(pt.list_price, 0.0)              AS precio_base
            FROM product_template pt
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE {where_clause}
            ORDER BY 2
            LIMIT %s OFFSET %s
        """
        cr.execute(rows_query, [lang] + params + [per_page, offset])
        templates = cr.dictfetchall()

        items = self._get_items(pl_ids, [t["id"] for t in templates])

        rows = []
        for t in templates:
            base = float(t["precio_base"] or 0.0)
            prices = {}
            max_diff = 0.0
            for p in pricelists:
                item_price = self._compute_item_price(items.get((p["id"], t["id"])), base)
                defined = item_price is not None
                price = item_price if defined else base
                diff = self._sane_diff(price, base) if defined else None
                if diff is not None and abs(diff) > abs(max_diff):
                    max_diff = diff
                prices[str(p["id"])] = {"price": price, "defined": defined, "diff": diff or 0.0}
            rows.append({
                "producto": t["producto"],
                "categoria": t["categoria"],
                "precio_base": round(base, 2),
                "prices": prices,
                "max_diff": max_diff,
            })

        return {
            "columns": columns,
            "rows": rows,
            "page": page,
            "pages": total_pages,
            "total": total_rows,
        }

    @http.route('/pricelist_management_metrics/metrics', type='json', auth='user')
    def get_metrics(self, category='all', product='all', pricelist='all', limit=20, **kwargs):
        """KPIs globales y top de productos con mayor diferencia base vs lista."""
        self._check_access()
        cr = request.env.cr
        lang = self._get_lang()

        pricelists = self._get_pricelists(pricelist)
        empty = {
            "kpis": {
                "total_products": 0,
                "products_with_override": 0,
                "avg_diff_percent": 0.0,
                "max_diff_percent": 0.0,
                "max_diff_product": "—",
                "pricelist_count": len(pricelists),
            },
            "top_differences": {"labels": [], "bases": [], "datasets": []},
        }
        if not pricelists:
            return empty
        pl_ids = tuple(p["id"] for p in pricelists)

        where_clause, params = self._build_template_where(category, product)

        # 1. Total de productos activos vendibles bajo los filtros
        cr.execute(f"""
            SELECT COUNT(*)
            FROM product_template pt
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE {where_clause}
        """, params)
        total_products = cr.fetchone()[0] or 0

        # 2. Reglas vigentes con datos del producto (solo plantillas con precio de lista)
        query = f"""
            SELECT pli.pricelist_id,
                   COALESCE(pp.product_tmpl_id, pli.product_tmpl_id) AS tmpl_id,
                   pli.applied_on,
                   pli.compute_price,
                   pli.fixed_price,
                   pli.percent_price,
                   COALESCE(pt.name->>%s, pt.name->>'en_US') AS producto,
                   COALESCE(pt.list_price, 0.0)              AS precio_base
            FROM product_pricelist_item pli
            LEFT JOIN product_product pp ON pp.id = pli.product_id
            JOIN product_template pt ON pt.id = COALESCE(pp.product_tmpl_id, pli.product_tmpl_id)
            LEFT JOIN product_category ic ON ic.id = pt.categ_id
            WHERE {where_clause}
              AND pli.pricelist_id IN %s
              AND pli.applied_on IN ('1_product', '0_product_variant')
              AND COALESCE(pli.min_quantity, 0) <= 1
              AND (pli.date_start IS NULL OR pli.date_start <= NOW())
              AND (pli.date_end IS NULL OR pli.date_end >= NOW())
            ORDER BY pli.applied_on, pli.id
        """
        cr.execute(query, [lang] + params + [pl_ids])

        # Consolidar una regla por (lista, plantilla), priorizando reglas de variante
        products_map = {}
        for row in cr.dictfetchall():
            key = (row['pricelist_id'], row['tmpl_id'])
            tmpl = products_map.setdefault(row['tmpl_id'], {
                "producto": row["producto"],
                "precio_base": float(row["precio_base"] or 0.0),
                "items": {},
            })
            if key[0] not in tmpl["items"]:
                tmpl["items"][key[0]] = row

        # 3. Calcular diferencias por producto y lista
        diff_rows = []
        all_diffs = []
        products_with_override = 0
        for tmpl_id, data in products_map.items():
            base = data["precio_base"]
            diffs = {}
            max_diff = 0.0
            has_override = False
            for p in pricelists:
                price = self._compute_item_price(data["items"].get(p["id"]), base)
                if price is None:
                    continue
                has_override = True
                diff = self._sane_diff(price, base)
                if diff is None:
                    # Precio base no cargado o dato basura: no comparable
                    continue
                diffs[p["id"]] = {"price": price, "diff": diff}
                all_diffs.append(abs(diff))
                if abs(diff) > abs(max_diff):
                    max_diff = diff
            if has_override:
                products_with_override += 1
            if diffs:
                diff_rows.append({
                    "producto": data["producto"],
                    "precio_base": round(base, 2),
                    "diffs": diffs,
                    "max_diff": max_diff,
                })

        avg_diff = round(sum(all_diffs) / len(all_diffs), 2) if all_diffs else 0.0

        max_diff_percent = 0.0
        max_diff_product = "—"
        for r in diff_rows:
            if abs(r["max_diff"]) > abs(max_diff_percent):
                max_diff_percent = r["max_diff"]
                max_diff_product = r["producto"]

        # 4. Top N productos con mayor diferencia absoluta
        limit = int(limit or 20)
        top = sorted(diff_rows, key=lambda r: abs(r["max_diff"]), reverse=True)[:limit]
        datasets = []
        for p in pricelists:
            values = [r["diffs"].get(p["id"], {}).get("diff") for r in top]
            prices = [r["diffs"].get(p["id"], {}).get("price") for r in top]
            if any(v is not None for v in values):
                datasets.append({
                    "pricelist": p["nombre"] + (f" ({p['empresa']})" if p["empresa"] else ""),
                    "values": values,
                    "prices": prices,
                })

        return {
            "kpis": {
                "total_products": total_products,
                "products_with_override": products_with_override,
                "avg_diff_percent": avg_diff,
                "max_diff_percent": max_diff_percent,
                "max_diff_product": max_diff_product,
                "pricelist_count": len(pricelists),
            },
            "top_differences": {
                "labels": [r["producto"] for r in top],
                "bases": [r["precio_base"] for r in top],
                "datasets": datasets,
            },
        }
